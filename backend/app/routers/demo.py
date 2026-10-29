"""Hackathon demonstration mode endpoints.

These endpoints provide clearly-labelled synthetic farm data for judging and
demonstration purposes. They are:

* Clearly labelled ``is_demo: true`` throughout.
* Scored by the real decision engine using its documented, crop-specific
  irrigation rule — recommendations are computed, not hardcoded.
* Independent of Supabase — a judge can use them without registering.
* Not mixed with real user data.

Endpoints:
    GET /api/demo/farms          — available demo farm profiles.
    GET /api/demo/farm/{id}      — one demo farm's full profile + sensors.
    POST /api/demo/plan          — run the decision engine on a demo farm.
    POST /api/demo/sensor        — adjust a simulated sensor reading and re-plan.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Path

from app import decision_engine, weather as weather_module
from app.errors import AppError, NotFoundError
from app.weather import WeatherUnavailableError

logger = logging.getLogger("farmiq.demo")
router = APIRouter()

# ── Synthetic demo farms ──────────────────────────────────────────────────────
# These represent realistic farm profiles across different Indian crop regions.
# NO real user data; clearly labelled is_demo=True.

DEMO_FARMS: dict[str, dict[str, Any]] = {
    "demo-nashik-grapes": {
        "id": "demo-nashik-grapes",
        "is_demo": True,
        "name": "Nashik Vineyard (Demo)",
        "location": "Nashik, Maharashtra",
        "latitude": 20.0059,
        "longitude": 73.7797,
        "area_value": 3.0,
        "area_unit": "acres",
        "soil_type": "Black (Vertisol)",
        "current_crop": "Grapes",
        "growth_stage": "Berry development",
        "irrigation_type": "drip",
        "description": "A 3-acre drip-irrigated vineyard near Nashik. "
                       "Black cotton soil, high water-holding capacity.",
    },
    "demo-solapur-soybean": {
        "id": "demo-solapur-soybean",
        "is_demo": True,
        "name": "Solapur Soybean Farm (Demo)",
        "location": "Solapur, Maharashtra",
        "latitude": 17.6805,
        "longitude": 75.9064,
        "area_value": 5.0,
        "area_unit": "acres",
        "soil_type": "Red (Alfisol)",
        "current_crop": "Soybean",
        "growth_stage": "Flowering",
        "irrigation_type": "borewell",
        "description": "5-acre soybean farm in Solapur district. "
                       "Red laterite soil, relies on monsoon + borewell backup.",
    },
    "demo-punjab-wheat": {
        "id": "demo-punjab-wheat",
        "is_demo": True,
        "name": "Punjab Wheat Farm (Demo)",
        "location": "Ludhiana, Punjab",
        "latitude": 30.9010,
        "longitude": 75.8573,
        "area_value": 8.0,
        "area_unit": "acres",
        "soil_type": "Alluvial",
        "current_crop": "Wheat",
        "growth_stage": "Grain Filling",
        "irrigation_type": "canal",
        "description": "8-acre wheat farm in Punjab. "
                       "Alluvial soil, canal-irrigated, high-input modern farming.",
    },
}

# Default simulated sensor readings per demo farm
_DEFAULT_SENSORS: dict[str, dict[str, Any]] = {
    "demo-nashik-grapes": {
        "device_id": "demo-sensor-nashik",
        "soil_moisture": 58.0,
        "soil_temperature": 26.0,
        "temperature": 29.0,
        "humidity": 68.0,
        "is_demo": True,
        "created_at": None,  # engine will note "no timestamp"
    },
    "demo-solapur-soybean": {
        "device_id": "demo-sensor-solapur",
        "soil_moisture": 22.0,   # intentionally low → will trigger irrigation alert
        "soil_temperature": 31.0,
        "temperature": 34.0,
        "humidity": 45.0,
        "is_demo": True,
        "created_at": None,
    },
    "demo-punjab-wheat": {
        "device_id": "demo-sensor-punjab",
        "soil_moisture": 48.0,
        "soil_temperature": 22.0,
        "temperature": 24.0,
        "humidity": 55.0,
        "is_demo": True,
        "created_at": None,
    },
}


def _get_demo_farm(farm_id: str) -> dict[str, Any]:
    f = DEMO_FARMS.get(farm_id)
    if f is None:
        raise NotFoundError(
            f"Demo farm '{farm_id}' not found. "
            f"Available: {list(DEMO_FARMS.keys())}"
        )
    return f


def _get_weather(farm: dict) -> Optional[dict]:
    try:
        weather = weather_module.build_report(
            float(farm["latitude"]),
            float(farm["longitude"]),
            place_name=farm.get("location"),
        )
        return weather
    except WeatherUnavailableError as exc:
        logger.info("Demo weather unavailable: %s", exc.detail)
        return None
    except Exception as exc:
        logger.warning("Demo weather unexpected error: %s", exc)
        return None


@router.get("/api/demo/farms")
def list_demo_farms():
    """List all available hackathon demonstration farms."""
    return {
        "is_demo": True,
        "notice": "These are synthetic demonstration farms for judging purposes only. "
                  "They do not represent real farms or real sensor data.",
        "farms": [
            {
                "id": f["id"],
                "name": f["name"],
                "location": f["location"],
                "crop": f["current_crop"],
                "soil_type": f["soil_type"],
                "area_value": f["area_value"],
                "area_unit": f["area_unit"],
                "description": f["description"],
            }
            for f in DEMO_FARMS.values()
        ],
    }


@router.get("/api/demo/farm/{farm_id}")
def get_demo_farm(
    farm_id: str = Path(..., description="Demo farm ID, e.g. demo-nashik-grapes"),
):
    """Full demo farm profile including default simulated sensor readings."""
    farm = _get_demo_farm(farm_id)
    sensor = _DEFAULT_SENSORS.get(farm_id, {})
    return {
        "is_demo": True,
        "farm": farm,
        "sensor": {**sensor, "is_demo": True},
        "notice": "Sensor values are simulated for demonstration. "
                  "Use POST /api/demo/sensor to adjust them.",
    }


@router.post("/api/demo/plan")
def demo_action_plan(
    farm_id: str = Body(..., embed=True),
    include_weather: bool = Body(True, embed=True),
):
    """
    Run the Farm Decision Engine on a demo farm.

    Returns a structured action plan combining the simulated sensor values,
    (optionally) live weather, and the engine's documented crop-specific
    rules. All results are clearly labelled is_demo=True.
    """
    farm = _get_demo_farm(farm_id)
    sensor = dict(_DEFAULT_SENSORS.get(farm_id, {}))

    weather = _get_weather(farm) if include_weather else None

    plan = decision_engine.build_plan(
        farm=farm,
        latest_sensor=sensor if sensor else None,
        weather=weather,
        ml_predictions={"irrigation": None, "fertilizer": None},
    )

    return {
        "is_demo": True,
        "notice": "This plan uses simulated sensor data and the documented, "
                  "crop-specific decision rules. Adjust sensor values with "
                  "POST /api/demo/sensor to see how recommendations change.",
        **plan,
        "farm": farm,
        "weather_source": (weather or {}).get("source"),
        "weather_fetched_at": (weather or {}).get("fetched_at"),
    }


@router.post("/api/demo/sensor")
def demo_custom_sensor(
    farm_id: str = Body(..., embed=True),
    soil_moisture: Optional[float] = Body(None, embed=True, ge=0, le=100),
    soil_temperature: Optional[float] = Body(None, embed=True, ge=0, le=60),
    temperature: Optional[float] = Body(None, embed=True, ge=-10, le=60),
    humidity: Optional[float] = Body(None, embed=True, ge=0, le=100),
    include_weather: bool = Body(True, embed=True),
):
    """
    Adjust simulated sensor values and re-run the decision engine.

    Judges can use this to observe how recommendations change when soil
    moisture drops, temperature rises, etc.
    """
    farm = _get_demo_farm(farm_id)
    base_sensor = dict(_DEFAULT_SENSORS.get(farm_id, {}))

    # Apply overrides
    if soil_moisture is not None:
        base_sensor["soil_moisture"] = soil_moisture
    if soil_temperature is not None:
        base_sensor["soil_temperature"] = soil_temperature
    if temperature is not None:
        base_sensor["temperature"] = temperature
    if humidity is not None:
        base_sensor["humidity"] = humidity

    weather = _get_weather(farm) if include_weather else None

    plan = decision_engine.build_plan(
        farm=farm,
        latest_sensor=base_sensor,
        weather=weather,
        ml_predictions={"irrigation": None, "fertilizer": None},
    )

    return {
        "is_demo": True,
        "sensor_values_used": {
            "soil_moisture": base_sensor.get("soil_moisture"),
            "soil_temperature": base_sensor.get("soil_temperature"),
            "temperature": base_sensor.get("temperature"),
            "humidity": base_sensor.get("humidity"),
        },
        "notice": "Simulated sensor values only. Real farm data may differ.",
        **plan,
        "farm": farm,
    }
