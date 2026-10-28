"""Weather auto-fill endpoints.

``GET /api/weather/current`` accepts EITHER coordinates (``lat``/``lon`` — used
with the browser's geolocation) OR a place name (``location`` — used with the
manual selector). It returns the current observation plus forecast and
historical rainfall, each in its own field, and a small ``autofill`` map the
frontend uses to populate the prediction form.

The endpoint is read-only and requires no authentication because it exposes no
user data, but it never leaks any credential — Open-Meteo is key-less. When the
provider is unreachable the request fails with HTTP 503 and the frontend keeps
the manual-entry form fully usable.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app import weather
from app.config import get_settings
from app.errors import AppError
from app.schemas import WeatherReport, WeatherReverseLocation

router = APIRouter()


@router.get("/api/weather/reverse", response_model=WeatherReverseLocation)
def reverse_location(
    lat: float = Query(..., ge=-90, le=90, description="Latitude"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude"),
):
    """Resolve coordinates to a place label, to pre-fill the farm location field.

    Read-only, no user data, so no authentication is required. Coordinates are
    validated by the query schema (out-of-range values are rejected with 422).
    A provider outage returns 503 - the frontend keeps the coordinates it
    already has and lets the farmer type the label manually.
    """
    if not get_settings().weather_enabled:
        raise AppError(503, "Location lookup is disabled on this server.")
    return weather.reverse_geocode(lat, lon)


@router.get("/api/weather/current", response_model=WeatherReport)
def current_weather(
    lat: float | None = Query(None, ge=-90, le=90, description="Latitude"),
    lon: float | None = Query(None, ge=-180, le=180, description="Longitude"),
    location: str | None = Query(None, min_length=2, max_length=120,
                                 description="Place name, e.g. 'Nashik'"),
):
    """Current weather + rainfall history/forecast for a location."""
    if not get_settings().weather_enabled:
        raise AppError(503, "Weather auto-fill is disabled on this server.")

    if (lat is None or lon is None) and not location:
        raise AppError(
            400,
            "Provide either lat/lon coordinates or a location name.",
        )

    place_name = None
    timezone_name = None
    if lat is None or lon is None:
        resolved = weather.geocode(location)
        lat, lon = resolved["latitude"], resolved["longitude"]
        place_name = resolved["name"]
        timezone_name = resolved.get("timezone")

    return weather.build_report(lat, lon, place_name=place_name, timezone_name=timezone_name)
