"""Sensor simulator / DEMO-mode tests (feature 4).

Covers the mandatory rules: every simulated reading is labelled DEMO DATA,
demo rows are stored with ``is_demo = true`` and never mix with hardware
readings, values are configurable, and sensor failures can be simulated.
"""
import pytest


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def _pair_device(app_client, h, name="ESP32 Demo Hub"):
    r = app_client.post("/api/devices/pair", json={"name": name, "config": "soil_sensor"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


NPK_CHANNELS = {"nitrogen", "phosphorous", "potassium", "ph", "temperature", "humidity", "soil_moisture"}


# ─────────────────────────────────────────────────────────────────────────
# Config + generation
# ─────────────────────────────────────────────────────────────────────────

def test_config_is_public_and_documents_channels(app_client):
    r = app_client.get("/api/simulator/config")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["label"] == "DEMO DATA"
    assert NPK_CHANNELS <= set(body["channels"])
    assert "soil_moisture_pct" in body["channels"]
    for name, spec in body["channels"].items():
        assert spec["min"] <= spec["max"], name
        assert spec["unit"]
    assert "simulated" in body["note"].lower()
    assert body["failure_modes"]


def test_generated_reading_is_labelled_demo_and_not_persisted_by_default(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/simulator/readings", json={"seed": 7}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["is_demo"] is True
    assert body["label"] == "DEMO DATA"
    assert body["persisted"] is False
    assert body["record_id"] is None
    assert body["failed_channels"] == []
    assert NPK_CHANNELS <= set(body["reading"])
    assert any("simulated" in n.lower() for n in body["notes"])
    assert any("hardware" in n.lower() for n in body["notes"])


def test_seeded_demo_readings_are_reproducible(app_client, fake_client):
    h = _auth(fake_client)
    first = app_client.post("/api/simulator/readings", json={"seed": 3}, headers=h).json()
    second = app_client.post("/api/simulator/readings", json={"seed": 3}, headers=h).json()
    assert first["reading"] == second["reading"]


def test_overrides_configure_exact_channel_values(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/simulator/readings",
                        json={"overrides": {"temperature": 31.5, "ph": 6.8, "nitrogen": 120}},
                        headers=h)
    assert r.status_code == 200, r.text
    reading = r.json()["reading"]
    assert reading["temperature"] == 31.5
    assert reading["ph"] == 6.8
    assert reading["nitrogen"] == 120


def test_unknown_channel_is_rejected(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/simulator/readings", json={"overrides": {"bogus_channel": 1}}, headers=h)
    assert r.status_code == 422, r.text
    assert "bogus_channel" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────
# Simulated sensor failures
# ─────────────────────────────────────────────────────────────────────────

def test_failure_injection_marks_channels_dead(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/simulator/readings",
                        json={"fail": ["humidity", "soil_moisture"], "seed": 5}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert {"humidity", "soil_moisture"} <= set(body["failed_channels"])
    assert "humidity" not in body["reading"]
    assert "soil_moisture" not in body["reading"]
    assert "temperature" in body["reading"], "healthy channels are unaffected"


def test_failing_all_channels_leaves_no_reading(app_client, fake_client):
    h = _auth(fake_client)
    body = app_client.post("/api/simulator/readings", json={"fail": ["all"]}, headers=h).json()
    assert body["reading"] == {}
    assert len(body["failed_channels"]) >= len(NPK_CHANNELS)
    # Still explicitly labelled as demo data even when every sensor is dark.
    assert body["label"] == "DEMO DATA" and body["is_demo"] is True


# ─────────────────────────────────────────────────────────────────────────
# Persistence — demo rows stay distinguishable from real rows
# ─────────────────────────────────────────────────────────────────────────

def test_persist_requires_a_device_id(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post("/api/simulator/readings", json={"persist": True}, headers=h)
    assert r.status_code == 400
    assert "device_id" in r.json()["detail"]


def test_persist_rejects_another_users_device(app_client, fake_client):
    owner = _auth(fake_client, "u1")
    stranger = _auth(fake_client, "u2")
    device = _pair_device(app_client, owner)

    r = app_client.post("/api/simulator/readings",
                        json={"persist": True, "device_id": device["id"]}, headers=stranger)
    assert r.status_code == 404


def test_demo_rows_are_stored_separately_from_real_readings(app_client, fake_client):
    h = _auth(fake_client)
    device = _pair_device(app_client, h)
    did = device["id"]

    demo = app_client.post("/api/simulator/readings",
                           json={"persist": True, "device_id": did, "seed": 11}, headers=h)
    assert demo.status_code == 200, demo.text
    demo_body = demo.json()
    assert demo_body["persisted"] is True and demo_body["record_id"]

    real = app_client.post("/api/sensor-readings/ingest",
                           json={"device_id": did, "soil_moisture": 55.0}, headers=h)
    assert real.status_code == 201, real.text
    real_id = real.json()["id"]
    assert real.json()["is_demo"] is False

    demo_rows = app_client.get("/api/sensor-readings", params={"source": "demo"}, headers=h).json()
    real_rows = app_client.get("/api/sensor-readings", params={"source": "real"}, headers=h).json()
    all_rows = app_client.get("/api/sensor-readings", headers=h).json()

    demo_ids = {r["id"] for r in demo_rows["items"]}
    real_ids = {r["id"] for r in real_rows["items"]}

    assert demo_body["record_id"] in demo_ids
    assert demo_body["record_id"] not in real_ids
    assert real_id in real_ids
    assert real_id not in demo_ids
    assert all(r["is_demo"] is True for r in demo_rows["items"])
    assert all(r["is_demo"] is False for r in real_rows["items"])
    assert {r["id"] for r in all_rows["items"]} == demo_ids | real_ids


def test_simulator_requires_authentication(app_client):
    assert app_client.post("/api/simulator/readings", json={}).status_code == 401


@pytest.mark.parametrize("channel", sorted(NPK_CHANNELS))
def test_every_documented_channel_can_be_generated(app_client, fake_client, channel):
    h = _auth(fake_client)
    body = app_client.post("/api/simulator/readings", json={"seed": 2}, headers=h).json()
    value = body["reading"][channel]
    assert isinstance(value, (int, float))
