"""Tests for the Farm Decision Engine (app/decision_engine.py).

All tests are unit tests — no DB, no network calls.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta


# ── Helpers ──────────────────────────────────────────────────────────────────

def _farm(crop="Wheat", stage="Flowering", location="Pune"):
    return {
        "id": "f1",
        "name": "Test Farm",
        "location": location,
        "current_crop": crop,
        "growth_stage": stage,
        "soil_type": "Black",
        "area_value": 2.5,
        "area_unit": "acres",
    }


def _sensor(moisture=50.0, soil_temp=26.0, temp=28.0, humidity=65.0, ts=None):
    ts = ts or datetime.now(timezone.utc).isoformat()
    return {
        "soil_moisture": moisture,
        "soil_temperature": soil_temp,
        "temperature": temp,
        "humidity": humidity,
        "created_at": ts,
        "is_demo": False,
    }


def _weather(temp=28.0, humidity=65.0, forecast_mm=5.0):
    return {
        "source": "Open-Meteo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "temperature_c": temp,
            "humidity_pct": humidity,
            "precipitation_mm": 0,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        "forecast_rainfall": {
            "total_mm": forecast_mm,
            "daily": [
                {"date": "2026-01-02", "precipitation_mm": forecast_mm, "rain_mm": forecast_mm},
                {"date": "2026-01-03", "precipitation_mm": 0, "rain_mm": 0},
            ],
        },
        "historical_rainfall": {"total_mm": 45.0, "days": 30, "daily": []},
    }


# ── Decision engine import ───────────────────────────────────────────────────

from app.decision_engine import (
    build_plan,
    PRIORITY_CRITICAL,
    PRIORITY_HIGH,
    PRIORITY_MODERATE,
    PRIORITY_LOW,
    _hours_since,
    _irrigation_rule,
    _weather_risk_rules,
    _data_freshness_warnings,
)


# ── _hours_since ─────────────────────────────────────────────────────────────

def test_hours_since_recent():
    ts = datetime.now(timezone.utc).isoformat()
    h = _hours_since(ts)
    assert h is not None and h < 0.1


def test_hours_since_old():
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    h = _hours_since(old)
    assert h is not None and 9.9 < h < 10.1


def test_hours_since_none():
    assert _hours_since(None) is None


def test_hours_since_bad_string():
    assert _hours_since("not-a-date") is None


# ── Irrigation rule ──────────────────────────────────────────────────────────

def test_irrigation_rule_dry_crop_recommends_irrigate():
    result = _irrigation_rule(
        sensor={"soil_moisture": 20.0},
        farm=_farm(crop="Wheat"),
        weather=None,
        ml_irrigation=None,
    )
    assert result is not None
    assert result["priority"] in (PRIORITY_CRITICAL, PRIORITY_HIGH)
    assert "irrigate" in result["action"].lower() or "irrigation" in result["reason"].lower()


def test_irrigation_rule_wet_crop_no_irrigate():
    result = _irrigation_rule(
        sensor={"soil_moisture": 70.0},
        farm=_farm(crop="Wheat"),
        weather=None,
        ml_irrigation=None,
    )
    assert result is not None
    assert result["priority"] == PRIORITY_LOW
    assert "no irrigation" in result["action"].lower()


def test_irrigation_rule_no_sensor_no_ml_returns_none():
    result = _irrigation_rule(
        sensor={},
        farm=_farm(),
        weather=None,
        ml_irrigation=None,
    )
    assert result is None


def test_irrigation_rule_ml_overrides_sensor():
    ml_irr = {"prediction": 1, "label": "Irrigate", "source": "model"}
    result = _irrigation_rule(
        sensor={"soil_moisture": 75.0},  # sensor says fine...
        farm=_farm(crop="Paddy"),
        weather=None,
        ml_irrigation=ml_irr,  # ...but ML says irrigate
    )
    assert result is not None
    assert result["priority"] in (PRIORITY_HIGH, PRIORITY_CRITICAL, PRIORITY_MODERATE)


def test_irrigation_rule_rain_coming_adds_warning():
    weather = _weather(forecast_mm=25.0)
    result = _irrigation_rule(
        sensor={"soil_moisture": 20.0},
        farm=_farm(crop="Wheat"),
        weather=weather,
        ml_irrigation=None,
    )
    assert result is not None
    assert any("rain" in w.lower() or "forecast" in w.lower() for w in result["warnings"])


def test_irrigation_critical_stage_raises_priority():
    result = _irrigation_rule(
        sensor={"soil_moisture": 20.0},
        farm=_farm(crop="Wheat", stage="flowering"),
        weather=None,
        ml_irrigation=None,
    )
    assert result is not None
    assert result["priority"] == PRIORITY_CRITICAL
    assert any("critical" in w.lower() or "flowering" in w.lower() for w in result["warnings"])


def test_irrigation_unknown_crop_uses_default():
    result = _irrigation_rule(
        sensor={"soil_moisture": 35.0},
        farm=_farm(crop="UnknownCrop"),
        weather=None,
        ml_irrigation=None,
    )
    # Should still produce a result with the default threshold
    assert result is not None


# ── Weather risk rules ───────────────────────────────────────────────────────

def test_weather_risk_extreme_heat():
    w = _weather(temp=42.0)
    actions = _weather_risk_rules(w)
    assert any("heat" in a["action"].lower() or "42" in a["action"] for a in actions)
    assert any(a["priority"] == PRIORITY_HIGH for a in actions)


def test_weather_risk_frost():
    w = _weather(temp=3.0)
    actions = _weather_risk_rules(w)
    assert any("frost" in a["action"].lower() or "protect" in a["action"].lower() for a in actions)


def test_weather_risk_heavy_rain():
    w = _weather()
    w["forecast_rainfall"]["daily"] = [
        {"date": "2026-01-02", "precipitation_mm": 65.0, "rain_mm": 60.0}
    ]
    actions = _weather_risk_rules(w)
    assert any("rain" in a["action"].lower() for a in actions)
    assert any(a["priority"] == PRIORITY_HIGH for a in actions)


def test_weather_risk_normal_returns_empty():
    w = _weather(temp=28.0)
    w["forecast_rainfall"]["daily"] = [
        {"date": "2026-01-02", "precipitation_mm": 5.0, "rain_mm": 5.0}
    ]
    actions = _weather_risk_rules(w)
    # No alerts for normal conditions
    assert len(actions) == 0


# ── Data freshness ───────────────────────────────────────────────────────────

def test_stale_sensor_warning():
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    items = _data_freshness_warnings(sensor_ts=old_ts, weather_ts=None)
    assert any("stale" in i["reason"].lower() or "sensor" in i["action"].lower() for i in items)


def test_no_sensor_low_priority_recommendation():
    items = _data_freshness_warnings(sensor_ts=None, weather_ts=None)
    assert any(i["priority"] == PRIORITY_LOW for i in items)
    assert any("sensor" in i["action"].lower() for i in items)


def test_fresh_sensor_no_warning():
    ts = datetime.now(timezone.utc).isoformat()
    items = _data_freshness_warnings(sensor_ts=ts, weather_ts=None)
    # Fresh sensor → no stale warning
    assert not any("stale" in i.get("reason", "").lower() for i in items)


# ── build_plan ───────────────────────────────────────────────────────────────

def test_build_plan_empty_farm():
    plan = build_plan(farm={}, latest_sensor=None, weather=None, ml_predictions={})
    assert "actions" in plan
    assert "summary" in plan
    assert "generated_at" in plan
    assert isinstance(plan["actions"], list)


def test_build_plan_actions_sorted_by_priority():
    plan = build_plan(
        farm=_farm(crop="Wheat", stage="flowering"),
        latest_sensor=_sensor(moisture=15.0, soil_temp=38.0),
        weather=_weather(temp=41.0),
        ml_predictions={},
    )
    actions = plan["actions"]
    assert len(actions) > 0
    priority_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3}
    for i in range(len(actions) - 1):
        assert priority_order.get(actions[i]["priority"], 9) <= priority_order.get(
            actions[i + 1]["priority"], 9
        ), f"Actions not sorted: {actions[i]['priority']} before {actions[i+1]['priority']}"


def test_build_plan_critical_summary():
    plan = build_plan(
        farm=_farm(crop="Wheat", stage="flowering"),
        latest_sensor=_sensor(moisture=12.0),
        weather=None,
        ml_predictions={},
    )
    assert plan["critical_count"] >= 1
    assert "critical" in plan["summary"].lower()


def test_build_plan_good_conditions_low_priority():
    plan = build_plan(
        farm=_farm(crop="Wheat"),
        latest_sensor=_sensor(moisture=65.0, soil_temp=24.0, temp=26.0),
        weather=_weather(temp=26.0, forecast_mm=5.0),
        ml_predictions={},
    )
    assert plan["critical_count"] == 0
    assert plan["high_count"] == 0


def test_build_plan_data_inputs_recorded():
    plan = build_plan(
        farm=_farm(crop="Wheat"),
        latest_sensor=_sensor(),
        weather=_weather(),
        ml_predictions={},
    )
    di = plan["data_inputs"]
    assert di["sensor_available"] is True
    assert di["weather_available"] is True
    assert di["crop"] == "Wheat"


def test_build_plan_no_weather_still_works():
    plan = build_plan(
        farm=_farm(crop="Maize"),
        latest_sensor=_sensor(moisture=30.0),
        weather=None,
        ml_predictions={},
    )
    assert plan["data_inputs"]["weather_available"] is False
    assert len(plan["actions"]) > 0


def test_build_plan_ml_irrigation_respected():
    ml = {"prediction": 1, "label": "Irrigate", "source": "model"}
    plan = build_plan(
        farm=_farm(crop="Paddy"),
        latest_sensor=_sensor(moisture=80.0),  # sensor says ok...
        weather=None,
        ml_predictions={"irrigation": ml},     # ...ML says irrigate
    )
    irr_actions = [a for a in plan["actions"] if a["category"] == "irrigation"]
    assert len(irr_actions) >= 1
    assert any("irrigate" in a["action"].lower() for a in irr_actions)


def test_build_plan_each_action_has_required_fields():
    plan = build_plan(
        farm=_farm(),
        latest_sensor=_sensor(moisture=15.0, soil_temp=37.0),
        weather=_weather(temp=41.0),
        ml_predictions={},
    )
    for action in plan["actions"]:
        assert "category" in action
        assert "action" in action
        assert "reason" in action
        assert "priority" in action
        assert action["priority"] in ("critical", "high", "moderate", "low")
        assert isinstance(action.get("warnings", []), list)
        assert isinstance(action.get("assumptions", []), list)
        assert isinstance(action.get("supporting_data", {}), dict)


def test_build_plan_hot_soil_generates_soil_action():
    plan = build_plan(
        farm=_farm(),
        latest_sensor=_sensor(soil_temp=37.0),
        weather=None,
        ml_predictions={},
    )
    soil_actions = [a for a in plan["actions"] if a["category"] == "soil"]
    assert len(soil_actions) >= 1
    assert any("mulch" in a["action"].lower() or "temperature" in a["reason"].lower()
               for a in soil_actions)


def test_build_plan_cold_soil_generates_sowing_warning():
    plan = build_plan(
        farm=_farm(),
        latest_sensor=_sensor(soil_temp=7.0),
        weather=None,
        ml_predictions={},
    )
    soil_actions = [a for a in plan["actions"] if a["category"] == "soil"]
    assert any("sow" in a["action"].lower() or "temperature" in a["reason"].lower()
               for a in soil_actions)


# ── Demo endpoint integration ────────────────────────────────────────────────

def test_demo_farms_list(app_client, fake_client):
    resp = app_client.get("/api/demo/farms")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_demo"] is True
    assert len(data["farms"]) >= 3
    for f in data["farms"]:
        assert "id" in f
        assert "name" in f
        assert "crop" in f


def test_demo_farm_detail(app_client, fake_client):
    resp = app_client.get("/api/demo/farm/demo-nashik-grapes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_demo"] is True
    assert data["farm"]["current_crop"] == "Grapes"
    assert data["sensor"]["is_demo"] is True


def test_demo_farm_not_found(app_client, fake_client):
    resp = app_client.get("/api/demo/farm/nonexistent-farm")
    assert resp.status_code == 404


def test_demo_plan_returns_plan(app_client, fake_client):
    resp = app_client.post("/api/demo/plan", json={
        "farm_id": "demo-solapur-soybean",
        "include_weather": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_demo"] is True
    assert "actions" in data
    assert "summary" in data
    assert isinstance(data["actions"], list)


def test_demo_plan_low_moisture_triggers_irrigation(app_client, fake_client):
    """Solapur demo farm has soil_moisture=22 (intentionally low)."""
    resp = app_client.post("/api/demo/plan", json={
        "farm_id": "demo-solapur-soybean",
        "include_weather": False,
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    irr_actions = [a for a in actions if a["category"] == "irrigation"]
    assert len(irr_actions) >= 1


def test_demo_sensor_override_changes_recommendations(app_client, fake_client):
    """Setting soil_moisture very high should reduce irrigation urgency."""
    resp_dry = app_client.post("/api/demo/sensor", json={
        "farm_id": "demo-solapur-soybean",
        "soil_moisture": 10.0,
        "include_weather": False,
    })
    resp_wet = app_client.post("/api/demo/sensor", json={
        "farm_id": "demo-solapur-soybean",
        "soil_moisture": 80.0,
        "include_weather": False,
    })
    assert resp_dry.status_code == 200
    assert resp_wet.status_code == 200

    dry_actions = resp_dry.json()["actions"]
    wet_actions = resp_wet.json()["actions"]

    dry_priorities = {a["priority"] for a in dry_actions if a["category"] == "irrigation"}
    wet_priorities = {a["priority"] for a in wet_actions if a["category"] == "irrigation"}

    # Dry should be higher priority than wet
    assert "critical" in dry_priorities or "high" in dry_priorities
    assert "low" in wet_priorities


def test_demo_sensor_invalid_farm(app_client, fake_client):
    resp = app_client.post("/api/demo/sensor", json={
        "farm_id": "invalid-demo-id",
        "soil_moisture": 20.0,
        "include_weather": False,
    })
    assert resp.status_code == 404


def test_demo_dashboard_plan_requires_auth(app_client, fake_client):
    """Real dashboard plan requires authentication; demo does not."""
    resp = app_client.get("/api/dashboard/plan")
    assert resp.status_code == 401   # no auth header
