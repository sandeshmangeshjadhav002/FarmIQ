"""Tests for the Alerts & Notifications module (§11).

Two layers:

* **Rule engine** (`app/alerts_service.py`) — pure-function tests with a fixed
  ``now``, covering every rule, the "no data means no alert" guarantee, demo
  propagation and de-duplication keys.
* **API** (`/api/alerts/*`) — auth enforcement, refresh persistence,
  de-duplication across refreshes, read/unread state and ownership isolation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import alerts_service

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _iso(hours_ago: float = 0.0) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _ctx(**overrides):
    base = {
        "devices": [],
        "latest_reading_by_device": {},
        "latest_assessment": None,
        "latest_predictions": [],
    }
    base.update(overrides)
    return base


def _keys(drafts):
    return [d["dedup_key"] for d in drafts]


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — no data
# ─────────────────────────────────────────────────────────────────────────

def test_empty_context_produces_no_alerts():
    assert alerts_service.derive_alerts(_ctx(), now=NOW) == []


def test_device_without_contact_timestamp_produces_no_alert():
    """A paired device with no recorded contact must not raise an alert."""
    device = {"id": "d1", "name": "Probe", "is_online": True, "last_seen_at": None}
    assert alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW) == []


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — sensor connectivity
# ─────────────────────────────────────────────────────────────────────────

def test_offline_device_raises_high_priority_alert():
    device = {"id": "d1", "name": "Soil probe A", "is_online": True,
              "last_seen_at": _iso(7.0)}
    drafts = alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW)
    assert len(drafts) == 1
    alert = drafts[0]
    assert alert["kind"] == "sensor"
    assert alert["priority"] == "high"
    assert alert["dedup_key"] == "sensor_offline:d1"
    assert "Soil probe A" in alert["title"]
    assert "7.0 h" in alert["reason"]


def test_stale_device_raises_medium_priority_alert():
    device = {"id": "d2", "name": "Weather node", "is_online": True,
              "last_seen_at": _iso(2.0)}
    drafts = alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["priority"] == "medium"
    assert drafts[0]["dedup_key"] == "sensor_stale:d2"


def test_fresh_device_produces_no_alert():
    device = {"id": "d3", "name": "Probe", "is_online": True, "last_seen_at": _iso(0.2)}
    assert alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW) == []


def test_explicitly_offline_device_alerts_even_when_recent():
    device = {"id": "d4", "name": "Pump", "is_online": False, "last_seen_at": _iso(0.1)}
    drafts = alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["priority"] == "high"
    assert drafts[0]["dedup_key"] == "sensor_offline:d4"


def test_offline_and_stale_are_mutually_exclusive():
    """A disconnected device must not also raise a stale-reading alert."""
    device = {"id": "d5", "name": "Probe", "is_online": True, "last_seen_at": _iso(9.0)}
    keys = _keys(alerts_service.derive_alerts(_ctx(devices=[device]), now=NOW))
    assert keys == ["sensor_offline:d5"]


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — reading plausibility
# ─────────────────────────────────────────────────────────────────────────

def test_implausible_values_are_flagged():
    device = {"id": "d6", "name": "Probe", "is_online": True, "last_seen_at": _iso(0.2)}
    reading = {"id": "r1", "ph": 22.0, "soil_moisture": 3400.0, "humidity": 55.0}
    drafts = alerts_service.derive_alerts(
        _ctx(devices=[device], latest_reading_by_device={"d6": reading}), now=NOW
    )
    assert len(drafts) == 1
    assert drafts[0]["dedup_key"] == "sensor_invalid:d6"
    assert "ph" in drafts[0]["body"]
    assert "soil_moisture" in drafts[0]["body"]
    assert "humidity" not in drafts[0]["body"]


def test_plausible_reading_is_not_flagged():
    device = {"id": "d7", "name": "Probe", "is_online": True, "last_seen_at": _iso(0.2)}
    reading = {"id": "r2", "ph": 6.5, "soil_moisture": 900.0, "humidity": 61.0}
    drafts = alerts_service.derive_alerts(
        _ctx(devices=[device], latest_reading_by_device={"d7": reading}), now=NOW
    )
    assert drafts == []


def test_demo_reading_marks_the_alert_as_demo():
    device = {"id": "d8", "name": "Demo probe", "is_online": True, "last_seen_at": _iso(0.2)}
    reading = {"id": "r3", "ph": 99.0, "is_demo": True}
    drafts = alerts_service.derive_alerts(
        _ctx(devices=[device], latest_reading_by_device={"d8": reading}), now=NOW
    )
    assert len(drafts) == 1
    assert drafts[0]["is_demo"] is True


def test_real_reading_is_not_marked_demo():
    device = {"id": "d9", "name": "Probe", "is_online": True, "last_seen_at": _iso(0.2)}
    reading = {"id": "r4", "ph": 99.0, "is_demo": False}
    drafts = alerts_service.derive_alerts(
        _ctx(devices=[device], latest_reading_by_device={"d9": reading}), now=NOW
    )
    assert drafts[0]["is_demo"] is False


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — irrigation / drought
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "severity,expected_priority",
    [("extreme", "critical"), ("severe", "high")],
)
def test_drought_severity_raises_irrigation_alert(severity, expected_priority):
    assessment = {"id": "a1", "crop": "Soybean", "location": "Solapur",
                  "drought_severity": severity,
                  "drought_severity_reason": "Very low rainfall with no water source."}
    drafts = alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "irrigation"
    assert drafts[0]["priority"] == expected_priority
    assert drafts[0]["dedup_key"] == "irrigation:a1"
    assert "Soybean" in drafts[0]["title"]


@pytest.mark.parametrize("severity", ["none", "mild", "moderate"])
def test_mild_severity_raises_no_irrigation_alert(severity):
    assessment = {"id": "a2", "crop": "Cotton", "drought_severity": severity}
    assert alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW) == []


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — weather
# ─────────────────────────────────────────────────────────────────────────

def test_heavy_rain_forecast_raises_weather_alert():
    assessment = {"id": "a3", "location": "Nashik", "drought_severity": "none",
                  "weather": {"fetched": True, "forecast_rain_7d_mm": 62.0}}
    drafts = alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "weather"
    assert drafts[0]["priority"] == "high"
    assert drafts[0]["dedup_key"] == "weather_rain:a3"
    assert "62" in drafts[0]["body"]


def test_low_recorded_rainfall_raises_weather_alert():
    assessment = {"id": "a4", "location": "Pune", "drought_severity": "none",
                  "weather": {"fetched": True, "forecast_rain_7d_mm": 4.0,
                              "historical_rain_mm": 3.0, "historical_days": 30}}
    drafts = alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["priority"] == "medium"
    assert drafts[0]["dedup_key"] == "weather_dry:a4"


def test_unavailable_weather_produces_no_weather_alert():
    """An unfetched forecast must never be turned into a weather alert."""
    assessment = {"id": "a5", "drought_severity": "none",
                  "weather": {"fetched": False, "forecast_rain_7d_mm": None}}
    assert alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW) == []


def test_normal_weather_produces_no_weather_alert():
    assessment = {"id": "a6", "drought_severity": "none",
                  "weather": {"fetched": True, "forecast_rain_7d_mm": 12.0,
                              "historical_rain_mm": 45.0}}
    assert alerts_service.derive_alerts(_ctx(latest_assessment=assessment), now=NOW) == []


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — predictions
# ─────────────────────────────────────────────────────────────────────────

def test_baseline_prediction_raises_alert():
    predictions = [{"domain": "crop", "output": {"source": "baseline"}}]
    drafts = alerts_service.derive_alerts(_ctx(latest_predictions=predictions), now=NOW)
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "prediction"
    assert drafts[0]["priority"] == "low"
    assert drafts[0]["dedup_key"] == "prediction_baseline:crop"


def test_model_prediction_raises_no_alert():
    predictions = [{"domain": "crop", "output": {"source": "model"}}]
    assert alerts_service.derive_alerts(_ctx(latest_predictions=predictions), now=NOW) == []


def test_repeated_baseline_predictions_collapse_to_one_alert():
    predictions = [
        {"domain": "yield", "output": {"source": "baseline"}},
        {"domain": "yield", "output": {"source": "baseline"}},
    ]
    drafts = alerts_service.derive_alerts(_ctx(latest_predictions=predictions), now=NOW)
    assert _keys(drafts) == ["prediction_baseline:yield"]


# ─────────────────────────────────────────────────────────────────────────
# Rule engine — ordering
# ─────────────────────────────────────────────────────────────────────────

def test_drafts_are_ordered_by_priority():
    device = {"id": "d10", "name": "Probe", "is_online": True, "last_seen_at": _iso(7.0)}
    assessment = {"id": "a7", "crop": "Wheat", "drought_severity": "extreme",
                  "weather": {"fetched": True, "forecast_rain_7d_mm": 80.0}}
    predictions = [{"domain": "crop", "output": {"source": "baseline"}}]
    drafts = alerts_service.derive_alerts(
        _ctx(devices=[device], latest_assessment=assessment, latest_predictions=predictions),
        now=NOW,
    )
    priorities = [d["priority"] for d in drafts]
    assert priorities == ["critical", "high", "high", "low"]


def test_invalid_channels_helper():
    assert alerts_service.invalid_channels({"ph": 7.0, "humidity": 101.0}) == ["humidity"]
    assert alerts_service.invalid_channels({"ph": "bad"}) == ["ph"]
    assert alerts_service.invalid_channels({}) == []


# ─────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────

def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid)
    return fake_client.auth_header(uid)


def _seed_offline_device(fake_client, uid="u1", device_id="d1"):
    fake_client.tables.setdefault("devices", []).append({
        "id": device_id,
        "owner_id": uid,
        "name": "Soil probe A",
        "farm_id": None,
        "config": "soil_sensor",
        "is_online": True,
        "last_seen_at": _iso(9.0),
        "created_at": _iso(100.0),
    })


def test_alerts_require_authentication(app_client):
    assert app_client.get("/api/alerts").status_code == 401
    assert app_client.post("/api/alerts/refresh").status_code == 401
    assert app_client.post("/api/alerts/read-all").status_code == 401


def test_refresh_with_no_data_returns_empty_list(app_client, fake_client):
    headers = _auth(fake_client)
    res = app_client.post("/api/alerts/refresh", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body == {"total": 0, "unread": 0, "items": []}


def test_refresh_derives_alerts_from_device_data(app_client, fake_client):
    headers = _auth(fake_client)
    _seed_offline_device(fake_client)

    body = app_client.post("/api/alerts/refresh", headers=headers).json()
    assert body["total"] == 1
    assert body["unread"] == 1
    alert = body["items"][0]
    assert alert["kind"] == "sensor"
    assert alert["priority"] == "high"
    assert alert["is_read"] is False
    assert alert["is_demo"] is False
    assert alert["created_at"]


def test_refresh_twice_does_not_duplicate(app_client, fake_client):
    headers = _auth(fake_client)
    _seed_offline_device(fake_client)

    app_client.post("/api/alerts/refresh", headers=headers)
    body = app_client.post("/api/alerts/refresh", headers=headers).json()
    assert body["total"] == 1


def test_marking_an_alert_read_updates_the_unread_count(app_client, fake_client):
    headers = _auth(fake_client)
    _seed_offline_device(fake_client)
    alert_id = app_client.post("/api/alerts/refresh", headers=headers).json()["items"][0]["id"]

    body = app_client.patch(
        f"/api/alerts/{alert_id}", headers=headers, json={"is_read": True}
    ).json()
    assert body["unread"] == 0
    assert body["items"][0]["is_read"] is True

    # Toggling back must work too.
    body = app_client.patch(
        f"/api/alerts/{alert_id}", headers=headers, json={"is_read": False}
    ).json()
    assert body["unread"] == 1


def test_refresh_preserves_read_state(app_client, fake_client):
    """Re-deriving an alert must not silently mark it unread again."""
    headers = _auth(fake_client)
    _seed_offline_device(fake_client)
    alert_id = app_client.post("/api/alerts/refresh", headers=headers).json()["items"][0]["id"]
    app_client.patch(f"/api/alerts/{alert_id}", headers=headers, json={"is_read": True})

    body = app_client.post("/api/alerts/refresh", headers=headers).json()
    assert body["unread"] == 0
    assert body["items"][0]["is_read"] is True


def test_read_all_marks_every_alert(app_client, fake_client):
    headers = _auth(fake_client)
    _seed_offline_device(fake_client, device_id="d1")
    _seed_offline_device(fake_client, device_id="d2")
    app_client.post("/api/alerts/refresh", headers=headers)

    body = app_client.post("/api/alerts/read-all", headers=headers).json()
    assert body["updated"] == 2
    assert app_client.get("/api/alerts", headers=headers).json()["unread"] == 0


def test_unknown_alert_cannot_be_marked_read(app_client, fake_client):
    headers = _auth(fake_client)
    res = app_client.patch(
        "/api/alerts/does-not-exist", headers=headers, json={"is_read": True}
    )
    assert res.status_code == 404


def test_alerts_are_isolated_per_user(app_client, fake_client):
    headers_a = _auth(fake_client, uid="u1")
    _seed_offline_device(fake_client, uid="u1")
    app_client.post("/api/alerts/refresh", headers=headers_a)

    # A second user with no data sees nothing.
    fake_client.seed_profile(uid="u2", email="other@example.com", mobile="+919000000002")
    headers_b = fake_client.auth_header("u2")
    body = app_client.get("/api/alerts", headers=headers_b).json()
    assert body == {"total": 0, "unread": 0, "items": []}


def test_unread_only_filter(app_client, fake_client):
    headers = _auth(fake_client)
    _seed_offline_device(fake_client, device_id="d1")
    _seed_offline_device(fake_client, device_id="d2")
    app_client.post("/api/alerts/refresh", headers=headers)
    first = app_client.get("/api/alerts", headers=headers).json()["items"][0]["id"]
    app_client.patch(f"/api/alerts/{first}", headers=headers, json={"is_read": True})

    body = app_client.get("/api/alerts?unread_only=true", headers=headers).json()
    assert body["total"] == 1
    assert body["unread"] == 1
