"""Sensor ingestion + history tests (user-token and device-token auth)."""


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def _pair_device(app_client, h, name="ESP32 Field Hub"):
    r = app_client.post("/api/devices/pair", json={"name": name, "config": "soil_sensor"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_ingest_via_user_token(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    did = device["id"]
    body = {"device_id": did, "soil_moisture": 62.0, "temperature": 27.0, "humidity": 71.0}
    r = app_client.post("/api/sensor-readings/ingest", json=body, headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["device_id"] == did
    assert out["soil_moisture"] == 62.0
    assert out["owner_id"] == "u1"


def test_ingest_via_device_token(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    did, token = device["id"], device["device_token"]
    body = {"device_id": did, "soil_moisture": 55.0}
    headers = {"Authorization": f"Bearer {token}", "X-Device-Id": did}
    r = app_client.post("/api/sensor-readings/ingest", json=body, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["device_id"] == did


def test_ingest_bad_device_token(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    body = {"device_id": device["id"], "soil_moisture": 10.0}
    headers = {"Authorization": "Bearer wrong-token", "X-Device-Id": device["id"]}
    assert app_client.post("/api/sensor-readings/ingest", json=body, headers=headers).status_code == 401


def test_ingest_device_id_mismatch(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    body = {"device_id": "some-other-id", "soil_moisture": 10.0}
    headers = {"Authorization": f"Bearer {device['device_token']}", "X-Device-Id": device["id"]}
    assert app_client.post("/api/sensor-readings/ingest", json=body, headers=headers).status_code == 400


def test_list_readings(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    app_client.post("/api/sensor-readings/ingest",
                    json={"device_id": device["id"], "soil_moisture": 40.0}, headers=h)
    r = app_client.get("/api/sensor-readings", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_ingest_requires_some_auth(app_client):
    body = {"device_id": "x", "soil_moisture": 10.0}
    assert app_client.post("/api/sensor-readings/ingest", json=body).status_code == 401


# ── BME680 air measurements ──────────────────────────────────────────────────

def test_ingest_stores_bme680_pressure(app_client, fake_client):
    """An ESP32 + BME680 node's pressure reading must be persisted, not dropped."""
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    did = device["id"]
    body = {
        "device_id": did,
        "temperature": 28.4,
        "humidity": 61.2,
        "pressure": 1008.3,
    }
    headers = {"Authorization": f"Bearer {device['device_token']}", "X-Device-Id": did}
    r = app_client.post("/api/sensor-readings/ingest", json=body, headers=headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["pressure"] == 1008.3
    assert out["temperature"] == 28.4
    assert out["humidity"] == 61.2
    assert out["is_demo"] is False

    stored = fake_client.tables["sensor_readings"][-1]
    assert stored["pressure"] == 1008.3


def test_ingest_without_pressure_leaves_it_null(app_client, fake_client):
    """A soil-only probe must not have a pressure value invented for it."""
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    r = app_client.post(
        "/api/sensor-readings/ingest",
        json={"device_id": device["id"], "soil_moisture": 44.0},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["pressure"] is None
    assert "pressure" not in fake_client.tables["sensor_readings"][-1]


def test_ingest_rejects_implausible_pressure(app_client, fake_client):
    """Outside 300–1100 hPa cannot come from a working BME680."""
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    for bad in (1200.0, 12.0, -1008.0):
        r = app_client.post(
            "/api/sensor-readings/ingest",
            json={"device_id": device["id"], "pressure": bad},
            headers=h,
        )
        assert r.status_code == 422, f"{bad} should be rejected"

