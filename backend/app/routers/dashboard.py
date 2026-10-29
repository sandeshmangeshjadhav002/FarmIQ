"""Dashboard summary + Farm Decision Engine endpoint.

GET /api/dashboard/summary  — counts + latest reading (backward-compatible).
GET /api/dashboard/plan     — full Farm Decision Engine action plan.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app import db, decision_engine, weather as weather_module
from app.auth import get_current_user
from app.errors import AppError
from app.schemas import DashboardSummary
from app.supabase_client import get_admin_client
from app.weather import WeatherUnavailableError

logger = logging.getLogger("farmiq.dashboard")
router = APIRouter()


@router.get("/api/dashboard/summary", response_model=DashboardSummary)
def summary(user=Depends(get_current_user), client=Depends(get_admin_client)):
    """Backward-compatible counts endpoint used by HomeScreen and FarmScreen."""
    return db.dashboard_summary(client, user.id)


@router.get("/api/dashboard/plan")
def action_plan(
    farm_id: Optional[str] = Query(None, description="Specific farm to plan for. Defaults to the user's first farm."),
    include_weather: bool = Query(True, description="Fetch current weather for the farm location."),
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
):
    """
    Farm Decision Engine: returns a structured daily action plan.

    Combines live sensor data, current weather, and the documented
    crop-specific irrigation rule. All recommendations include their data
    sources and freshness. Missing data is reported honestly —
    recommendations are never fabricated.
    """
    # 1. Resolve farm
    farm: dict[str, Any] = {}
    if farm_id:
        try:
            farm = db.get_farm(client, user.id, farm_id)
        except Exception:
            raise AppError(404, f"Farm '{farm_id}' not found or does not belong to you.")
    else:
        farms, _ = db.list_farms(client, user.id, limit=1)
        farm = farms[0] if farms else {}

    # 2. Latest sensor reading
    latest_sensor: Optional[dict] = None
    try:
        readings, _ = db.list_sensor_readings(
            client, user.id,
            farm_id=farm.get("id"),
            limit=1,
            is_demo=False,   # real hardware only for action plan
        )
        latest_sensor = readings[0] if readings else None
    except Exception as exc:
        logger.warning("Could not fetch sensor readings for plan: %s", exc)

    # 3. Weather (optional — gracefully skip if unavailable)
    weather: Optional[dict] = None
    if include_weather and farm.get("latitude") and farm.get("longitude"):
        try:
            weather = weather_module.build_report(
                float(farm["latitude"]),
                float(farm["longitude"]),
                place_name=farm.get("location"),
            )
        except WeatherUnavailableError as exc:
            logger.info("Weather unavailable for plan: %s", exc.detail)
        except Exception as exc:
            logger.warning("Unexpected weather error in plan: %s", exc)
    elif include_weather and farm.get("location"):
        try:
            geo = weather_module.geocode(farm["location"])
            weather = weather_module.build_report(
                geo["latitude"], geo["longitude"],
                place_name=geo.get("name"),
            )
        except WeatherUnavailableError as exc:
            logger.info("Weather unavailable for plan: %s", exc.detail)
        except Exception as exc:
            logger.warning("Unexpected weather error in plan: %s", exc)

    # 4. ML predictions.
    #
    # Irrigation is intentionally left to the decision engine's documented,
    # crop-specific soil-moisture rule. The trained irrigation classifier
    # expects a different input unit (raw ADC — see ml/validation.py) than the
    # percentage stored on a sensor reading, and its learned polarity is
    # inverted relative to these field semantics. Feeding it the reading would
    # override the rule with a wrong recommendation, so it is not used here;
    # the classifier remains available via /api/predictions/irrigation, where
    # inputs are validated against the model's real training range.
    # Fertilizer stays None until nutrient sensor data is available.
    ml_predictions: dict[str, Optional[dict]] = {
        "irrigation": None,
        "fertilizer": None,
    }

    # 5. Build plan
    plan = decision_engine.build_plan(
        farm=farm,
        latest_sensor=latest_sensor,
        weather=weather,
        ml_predictions=ml_predictions,
    )

    # Enrich with farm metadata for the frontend
    plan["farm"] = {
        "id": farm.get("id"),
        "name": farm.get("name"),
        "location": farm.get("location"),
        "current_crop": farm.get("current_crop"),
        "soil_type": farm.get("soil_type"),
        "area_value": farm.get("area_value"),
        "area_unit": farm.get("area_unit"),
    } if farm else None

    plan["weather_summary"] = _compact_weather(weather)
    plan["sensor_summary"] = _compact_sensor(latest_sensor)

    return plan


def _compact_weather(weather: Optional[dict]) -> Optional[dict]:
    if not weather:
        return None
    current = weather.get("current") or {}
    return {
        "temperature_c": current.get("temperature_c"),
        "humidity_pct": current.get("humidity_pct"),
        "rain_now_mm": current.get("precipitation_mm"),
        "forecast_rain_7d_mm": (weather.get("forecast_rainfall") or {}).get("total_mm"),
        "historical_rain_30d_mm": (weather.get("historical_rainfall") or {}).get("total_mm"),
        "observed_at": current.get("observed_at"),
        "source": weather.get("source"),
        "fetched_at": weather.get("fetched_at"),
        "location": (weather.get("location") or {}).get("name"),
    }


def _compact_sensor(sensor: Optional[dict]) -> Optional[dict]:
    if not sensor:
        return None
    return {
        "soil_moisture": sensor.get("soil_moisture"),
        "soil_temperature": sensor.get("soil_temperature"),
        "temperature": sensor.get("temperature"),
        "humidity": sensor.get("humidity"),
        "created_at": sensor.get("created_at"),
        "device_id": sensor.get("device_id"),
        "is_demo": sensor.get("is_demo", False),
    }
