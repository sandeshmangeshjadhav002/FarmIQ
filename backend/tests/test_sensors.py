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
