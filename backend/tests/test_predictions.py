"""Prediction endpoint tests.

These tests point the ML adapter at an empty temp models dir (``ml_tmp_models``)
so they are deterministic whether or not real model files exist locally:
crop/fertilizer/yield return 501 (ModelNotAvailable) and irrigation falls back
to the existing rule-based baseline (200). Prediction history is recorded for
successful calls.
"""

from app.errors import ModelNotAvailableError  # noqa: F401  (documents expected error)


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def test_irrigation_baseline(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    body = {"soil_moisture": 20.0, "temperature": 30.0, "humidity": 60.0,
            "crop_days": 10, "crop_type": "Paddy"}
    r = app_client.post("/api/predictions/irrigation", json=body, headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["domain"] == "irrigation"
    assert j["source"] == "baseline"
    assert j["prediction"] == 1  # 20 < 30 threshold -> irrigate
    assert j["label"] == "Irrigate"


def test_irrigation_baseline_no_irrigation(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    body = {"soil_moisture": 50.0, "temperature": 30.0, "humidity": 60.0, "crop_days": 10}
    r = app_client.post("/api/predictions/irrigation", json=body, headers=h)
    assert r.status_code == 200
    assert r.json()["prediction"] == 0  # 50 >= 30 -> no irrigation


def test_crop_501_without_model(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    body = {"N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80,
            "ph": 6.5, "rainfall": 200}
    r = app_client.post("/api/predictions/crop", json=body, headers=h)
    assert r.status_code == 501
    assert "model" in r.json()["detail"].lower()


def test_fertilizer_501_without_model(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    body = {"temparature": 26, "humidity": 60, "moisture": 40, "nitrogen": 80,
            "potassium": 20, "phosphorous": 30, "soil_type": "Loamy", "crop_type": "Wheat"}
    r = app_client.post("/api/predictions/fertilizer", json=body, headers=h)
    assert r.status_code == 501


def test_prediction_history_recorded(app_client, fake_client, ml_tmp_models):
    h = _auth(fake_client)
    app_client.post("/api/predictions/irrigation",
                    json={"soil_moisture": 20.0}, headers=h)
    r = app_client.get("/api/predictions", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert r.json()["items"][0]["domain"] == "irrigation"
