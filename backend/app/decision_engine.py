"""Farm Decision Engine — FarmIQ's core planning logic.

Takes available farm data (weather, sensors, ML predictions, farm profile) and
produces a structured daily action plan with prioritised recommendations.

Design rules:
* Every recommendation carries its data sources and freshness.
* Recommendations are never fabricated: if a required input is missing, the
  recommendation is omitted or marked as requiring that input.
* Conflict handling: when two signals disagree, the conservative action is taken
  and both signals are shown so the farmer understands the trade-off.
* Deterministic and testable: no LLM calls here. RAG is for conversational
  advice; decision rules live here and can be unit-tested.
* The engine is separate from all API routes; routes call `build_plan()`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("farmiq.decision")

# ── Priority levels ────────────────────────────────────────────────────────────
PRIORITY_CRITICAL = "critical"   # act today, crop at risk
PRIORITY_HIGH     = "high"       # act within 1–2 days
PRIORITY_MODERATE = "moderate"   # act this week
PRIORITY_LOW      = "low"        # informational / plan ahead


# ── Stale-data thresholds ──────────────────────────────────────────────────────
SENSOR_STALE_HOURS    = 6    # sensor reading older than this → stale warning
WEATHER_STALE_HOURS   = 12   # weather data older than this → stale warning


def _hours_since(iso_timestamp: Optional[str]) -> Optional[float]:
    """Hours since an ISO timestamp. Returns None if unparseable."""
    if not iso_timestamp:
        return None
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def _is_stale(iso_timestamp: Optional[str], threshold_hours: float) -> bool:
    h = _hours_since(iso_timestamp)
    return h is None or h > threshold_hours


def _fmt_hours(h: Optional[float]) -> str:
    if h is None:
        return "unknown time"
    if h < 1:
        return f"{int(h * 60)} minutes ago"
    if h < 24:
        return f"{h:.1f} hours ago"
    return f"{h / 24:.1f} days ago"


# ── Irrigation decision rules ─────────────────────────────────────────────────

# Crop-specific field capacity and wilting point (% volumetric soil moisture)
# These are broad defaults from ICAR guidelines; the decision errs conservative.
_CROP_MOISTURE_THRESHOLDS: dict[str, dict[str, float]] = {
    "Paddy":        {"irrigate_below": 55, "optimal_low": 60, "optimal_high": 80},
    "Ground Nuts":  {"irrigate_below": 40, "optimal_low": 50, "optimal_high": 70},
    "Wheat":        {"irrigate_below": 45, "optimal_low": 55, "optimal_high": 75},
    "Maize":        {"irrigate_below": 40, "optimal_low": 50, "optimal_high": 70},
    "Cotton":       {"irrigate_below": 38, "optimal_low": 48, "optimal_high": 68},
    "Tomato":       {"irrigate_below": 50, "optimal_low": 60, "optimal_high": 75},
    "Soybean":      {"irrigate_below": 42, "optimal_low": 52, "optimal_high": 72},
    "_default":     {"irrigate_below": 40, "optimal_low": 50, "optimal_high": 70},
}

_CRITICAL_GROWTH_STAGES = {
    "flowering", "grain filling", "pod filling", "boll formation",
    "fruit set", "heading", "jointing",
}


def _irrigation_rule(
    sensor: dict[str, Any],
    farm: dict[str, Any],
    weather: Optional[dict[str, Any]],
    ml_irrigation: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """
    Returns an irrigation action dict, or None if insufficient data.

    Uses the ML model when available, falls back to soil-moisture thresholds.
    """
    moisture = sensor.get("soil_moisture")
    crop = (farm.get("current_crop") or "").strip()
    stage = (farm.get("growth_stage") or "").strip().lower()
    thresholds = _CROP_MOISTURE_THRESHOLDS.get(crop, _CROP_MOISTURE_THRESHOLDS["_default"])

    # Forecast rainfall within next 48h — if significant rain is coming, delay.
    forecast_rain_48h = None
    if weather:
        daily = (weather.get("forecast_rainfall") or {}).get("daily") or []
        forecast_rain_48h = sum(
            (d.get("precipitation_mm") or 0) for d in daily[:2]
            if isinstance(d.get("precipitation_mm"), (int, float))
        )

    # Rain check: >10 mm expected within 48h → hold off irrigation
    rain_coming = forecast_rain_48h is not None and forecast_rain_48h > 10

    is_critical = any(s in stage for s in _CRITICAL_GROWTH_STAGES)

    supporting_data = {}
    assumptions = []
    warnings = []

    # Prioritise ML model output
    if ml_irrigation and ml_irrigation.get("prediction") is not None:
        should_irrigate = int(ml_irrigation["prediction"]) == 1
        source = ml_irrigation.get("source", "model")
        supporting_data["ml_prediction"] = ml_irrigation.get("label", str(ml_irrigation["prediction"]))
        supporting_data["ml_source"] = source
        if moisture is not None:
            supporting_data["soil_moisture_pct"] = moisture
    elif moisture is not None:
        # Rule-based fallback
        should_irrigate = moisture < thresholds["irrigate_below"]
        source = "threshold_rule"
        supporting_data["soil_moisture_pct"] = moisture
        supporting_data["threshold_pct"] = thresholds["irrigate_below"]
        assumptions.append(
            f"Threshold based on typical {crop or 'general crop'} requirements "
            f"(ICAR guidelines). Field capacity and wilting point vary by soil."
        )
    else:
        return None  # no data → no recommendation

    if moisture is None:
        assumptions.append("Soil moisture not available; decision based on ML model only.")

    if rain_coming:
        warnings.append(
            f"Forecast shows {forecast_rain_48h:.0f} mm within 48 h. "
            "If rain arrives, delay irrigation to avoid over-watering. "
            "Forecast is not guaranteed."
        )

    if should_irrigate and rain_coming:
        # Conservative: flag but don't force irrigate
        action = (
            "Irrigation may be needed, but significant rainfall is forecast. "
            "Monitor conditions and irrigate only if rain does not arrive."
        )
        priority = PRIORITY_MODERATE
        reason = (
            f"Soil moisture ({moisture:.0f}% " if moisture is not None else "ML model "
        ) + "suggests irrigation, but rain forecast exists. Confirm before irrigating."
    elif should_irrigate:
        action = f"Irrigate {crop or 'crop'} now." + (" Critical growth stage." if is_critical else "")
        priority = PRIORITY_CRITICAL if is_critical else PRIORITY_HIGH
        reason = (
            f"Soil moisture {moisture:.0f}% is below the {thresholds['irrigate_below']}% threshold."
            if moisture is not None else
            "ML irrigation model recommends irrigation."
        )
    else:
        action = f"No irrigation needed for {crop or 'crop'} at this time."
        priority = PRIORITY_LOW
        reason = (
            f"Soil moisture {moisture:.0f}% is within acceptable range."
            if moisture is not None else
            "ML irrigation model indicates no immediate need."
        )

    if is_critical and should_irrigate:
        warnings.append(
            f"Crop is at {stage} — a critical water-sensitive stage. "
            "Water stress now can cause permanent yield loss."
        )

    return {
        "category": "irrigation",
        "action": action,
        "reason": reason,
        "priority": priority,
        "supporting_data": supporting_data,
        "assumptions": assumptions,
        "warnings": warnings,
    }


# ── Soil health rules ─────────────────────────────────────────────────────────

def _soil_health_rule(
    sensor: dict[str, Any],
    farm: dict[str, Any],
    ml_fertilizer: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate soil-related action items from sensor + ML fertilizer prediction."""
    actions = []

    # Soil temperature alert
    soil_temp = sensor.get("soil_temperature")
    if soil_temp is not None:
        if soil_temp > 35:
            actions.append({
                "category": "soil",
                "action": "Apply mulch to reduce soil temperature.",
                "reason": f"Soil temperature {soil_temp:.1f}°C is above 35°C — "
                          "this can damage root systems and inhibit germination.",
                "priority": PRIORITY_HIGH,
                "supporting_data": {"soil_temperature_c": soil_temp},
                "assumptions": ["Measurement from in-field sensor."],
                "warnings": [],
            })
        elif soil_temp < 10:
            actions.append({
                "category": "soil",
                "action": "Delay sowing or transplanting until soil warms.",
                "reason": f"Soil temperature {soil_temp:.1f}°C is below 10°C — "
                          "most kharif crops require at least 15°C for germination.",
                "priority": PRIORITY_HIGH,
                "supporting_data": {"soil_temperature_c": soil_temp},
                "assumptions": ["Kharif crop temperature requirement per ICAR guidelines."],
                "warnings": [],
            })

    # Fertilizer recommendation from ML
    if ml_fertilizer and ml_fertilizer.get("prediction"):
        crop = farm.get("current_crop") or "your crop"
        actions.append({
            "category": "fertilizer",
            "action": f"Apply {ml_fertilizer['prediction']} fertilizer.",
            "reason": "ML model recommendation based on soil nutrient levels and crop type.",
            "priority": PRIORITY_MODERATE,
            "supporting_data": {"recommended_fertilizer": ml_fertilizer["prediction"],
                                 "ml_source": ml_fertilizer.get("source", "model")},
            "assumptions": [
                "Fertilizer type only — quantity should follow state KVK or ICAR dosage tables.",
                "Consult a local agronomist before large applications.",
            ],
            "warnings": [],
        })

    return actions


# ── Weather risk rules ────────────────────────────────────────────────────────

def _weather_risk_rules(weather: dict[str, Any]) -> list[dict[str, Any]]:
    """Check for temperature extremes and significant rainfall in the forecast."""
    actions = []
    current = weather.get("current") or {}
    temp = current.get("temperature_c")
    humidity = current.get("humidity_pct")

    if temp is not None:
        if temp > 40:
            actions.append({
                "category": "weather",
                "action": "Take protective measures against heat stress.",
                "reason": f"Current temperature {temp:.1f}°C exceeds 40°C. "
                          "Most field crops show heat stress above 38°C.",
                "priority": PRIORITY_HIGH,
                "supporting_data": {"temperature_c": temp},
                "assumptions": ["Current observation from Open-Meteo."],
                "warnings": ["Verify with local observation; Open-Meteo may differ from microclimate."],
            })
        elif temp < 5:
            actions.append({
                "category": "weather",
                "action": "Protect crops from frost risk.",
                "reason": f"Current temperature {temp:.1f}°C is near freezing. "
                          "Tender crops and seedlings can suffer frost damage below 2°C.",
                "priority": PRIORITY_HIGH,
                "supporting_data": {"temperature_c": temp},
                "assumptions": ["Current observation from Open-Meteo."],
                "warnings": ["Local frost timing can differ from regional forecast."],
            })

    # Heavy rain forecast
    daily = (weather.get("forecast_rainfall") or {}).get("daily") or []
    for day in daily[:3]:
        rain = day.get("precipitation_mm") or 0
        if isinstance(rain, (int, float)) and rain > 50:
            actions.append({
                "category": "weather",
                "action": f"Heavy rain forecast ({rain:.0f} mm) — check field drainage.",
                "reason": "Forecast of >50 mm/day can cause waterlogging in poorly drained fields.",
                "priority": PRIORITY_HIGH,
                "supporting_data": {
                    "forecast_date": day.get("date"),
                    "forecast_rain_mm": rain,
                },
                "assumptions": [],
                "warnings": [
                    "Forecast rainfall is not confirmed and may not reach your specific field.",
                ],
            })
            break

    return actions


# ── Data freshness warnings ───────────────────────────────────────────────────

def _data_freshness_warnings(
    sensor_ts: Optional[str],
    weather_ts: Optional[str],
) -> list[dict[str, Any]]:
    items = []
    s_hours = _hours_since(sensor_ts)
    if s_hours is not None and s_hours > SENSOR_STALE_HOURS:
        items.append({
            "category": "data_quality",
            "action": "Check sensor connection — readings may be stale.",
            "reason": f"Last sensor reading was {_fmt_hours(s_hours)}. "
                      f"Readings older than {SENSOR_STALE_HOURS} h may not reflect "
                      "current field conditions.",
            "priority": PRIORITY_MODERATE,
            "supporting_data": {"last_reading": sensor_ts},
            "assumptions": [],
            "warnings": [],
        })
    elif sensor_ts is None:
        items.append({
            "category": "data_quality",
            "action": "Connect a soil sensor to improve irrigation recommendations.",
            "reason": "No sensor data available. Recommendations are based on "
                      "weather and ML model defaults only.",
            "priority": PRIORITY_LOW,
            "supporting_data": {},
            "assumptions": [],
            "warnings": [],
        })

    if weather_ts and _is_stale(weather_ts, WEATHER_STALE_HOURS):
        items.append({
            "category": "data_quality",
            "action": "Refresh weather data.",
            "reason": f"Weather data is from {_fmt_hours(_hours_since(weather_ts))}. "
                      "Weather conditions may have changed.",
            "priority": PRIORITY_LOW,
            "supporting_data": {"weather_fetched_at": weather_ts},
            "assumptions": [],
            "warnings": [],
        })

    return items


# ── Priority ordering ─────────────────────────────────────────────────────────

_PRIORITY_ORDER = {PRIORITY_CRITICAL: 0, PRIORITY_HIGH: 1, PRIORITY_MODERATE: 2, PRIORITY_LOW: 3}


def _sort_actions(actions: list[dict]) -> list[dict]:
    return sorted(actions, key=lambda a: _PRIORITY_ORDER.get(a.get("priority", "low"), 4))


# ── Main entry point ─────────────────────────────────────────────────────────

def build_plan(
    farm: dict[str, Any],
    latest_sensor: Optional[dict[str, Any]],
    weather: Optional[dict[str, Any]],
    ml_predictions: dict[str, Optional[dict[str, Any]]],
) -> dict[str, Any]:
    """
    Build a structured daily farm action plan.

    Parameters
    ----------
    farm:
        Farm profile dict (from DB). May be empty ({}) for new users.
    latest_sensor:
        Most recent sensor reading dict, or None.
    weather:
        Weather report dict from app.weather.build_report(), or None.
    ml_predictions:
        Dict with keys 'irrigation', 'fertilizer', etc. Any may be None
        when the model or inputs are unavailable.

    Returns a dict with keys: actions, summary, data_inputs, generated_at.
    """
    sensor = latest_sensor or {}
    actions: list[dict[str, Any]] = []
    data_inputs: dict[str, Any] = {
        "farm_name": farm.get("name"),
        "crop": farm.get("current_crop"),
        "location": farm.get("location"),
        "sensor_available": latest_sensor is not None,
        "weather_available": weather is not None,
    }

    # 1. Irrigation
    irr_pred = ml_predictions.get("irrigation")
    irr_action = _irrigation_rule(sensor, farm, weather, irr_pred)
    if irr_action:
        actions.append(irr_action)

    # 2. Soil / fertilizer
    fert_pred = ml_predictions.get("fertilizer")
    soil_actions = _soil_health_rule(sensor, farm, fert_pred)
    actions.extend(soil_actions)

    # 3. Weather risks
    if weather:
        wx_actions = _weather_risk_rules(weather)
        actions.extend(wx_actions)

    # 4. Data freshness
    sensor_ts = sensor.get("created_at")
    weather_ts = (weather or {}).get("fetched_at")
    freshness_items = _data_freshness_warnings(sensor_ts, weather_ts)
    actions.extend(freshness_items)

    # Sort by priority
    actions = _sort_actions(actions)

    # Summary
    critical = sum(1 for a in actions if a["priority"] == PRIORITY_CRITICAL)
    high = sum(1 for a in actions if a["priority"] == PRIORITY_HIGH)

    if critical > 0:
        summary = f"{critical} critical action{'s' if critical > 1 else ''} needed today."
    elif high > 0:
        summary = f"{high} high-priority item{'s' if high > 1 else ''} need attention."
    elif actions:
        summary = "Farm conditions are acceptable. Review recommendations below."
    else:
        summary = "No farm data available yet. Add a farm and connect sensors to get personalised advice."

    return {
        "actions": actions,
        "summary": summary,
        "action_count": len(actions),
        "critical_count": critical,
        "high_count": high,
        "data_inputs": data_inputs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
