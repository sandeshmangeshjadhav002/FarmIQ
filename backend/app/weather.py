"""Weather look-up + auto-fill values for the ML prediction forms.

Data source: **Open-Meteo** (https://open-meteo.com) — a free, key-less API, so
no credential is stored and nothing has to be shared with the frontend.

Design rules enforced here (per the project requirements):

* The three rainfall concepts are kept strictly separate and are never mixed:
    - ``current.precipitation_mm`` — the observation right now,
    - ``forecast_rainfall``        — rain expected in the coming days,
    - ``historical_rainfall``      — rain that has already fallen (cumulative).
* The crop/fertilizer models were trained on **seasonal cumulative** rainfall
  (0–3000 mm, ``Crop_recommendation.csv``), so a single hour of drizzle is
  meaningless to them. The ``rainfall`` auto-fill value therefore comes from the
  *accumulated* historical total and is labelled as such — never from the
  current observation.
* Everything degrades gracefully: if Open-Meteo is unreachable the caller
  raises a 503 and the prediction forms stay fully usable with manual entry.

Nothing is fabricated: every number returned comes from the live API response.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.errors import AppError

logger = logging.getLogger("farmiq.weather")

_RAINFALL_AUTOFILL_NOTE = (
    "This is accumulated rainfall over the past {days} days from historical "
    "weather records — not today's rain. The crop model expects cumulative "
    "seasonal rainfall, so review this figure against your own field records."
)


class WeatherUnavailableError(AppError):
    """Raised when the upstream weather provider cannot be reached."""

    def __init__(self, detail: str):
        super().__init__(
            503,
            detail,
            hint=(
                "Weather auto-fill is optional — you can still type the values "
                "manually and run the prediction."
            ),
        )


# ─────────────────────────────────────────────────────────────────────────
# Low-level calls
# ─────────────────────────────────────────────────────────────────────────

def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": "FarmIQ/2.0"})


def geocode(location: str) -> dict[str, Any]:
    """Resolve a place name to coordinates via the Open-Meteo geocoding API."""
    settings = get_settings()
    url = f"{settings.weather_geocoding_url.rstrip('/')}/search"
    params = {"name": location, "count": 1, "language": "en", "format": "json"}
    try:
        with _client(settings.weather_timeout_seconds) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Geocoding failed for '%s': %s", location, exc)
        raise WeatherUnavailableError(
            "Could not reach the location lookup service. Enter coordinates or "
            "type the values manually."
        ) from exc

    results = payload.get("results") or []
    if not results:
        raise AppError(404, f"Location '{location}' could not be found.")
    top = results[0]
    return {
        "name": ", ".join(
            [p for p in (top.get("name"), top.get("admin1"), top.get("country")) if p]
        ),
        "latitude": float(top["latitude"]),
        "longitude": float(top["longitude"]),
        "timezone": top.get("timezone"),
    }


def fetch_weather(latitude: float, longitude: float, *, days: int = 7) -> dict[str, Any]:
    """Current observation + daily rainfall history/forecast for a coordinate."""
    settings = get_settings()
    url = f"{settings.weather_base_url.rstrip('/')}/forecast"
    history = settings.weather_history_days
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain",
        "daily": "precipitation_sum,rain_sum",
        "past_days": history,
        "forecast_days": days,
        "timezone": "auto",
    }
    try:
        with _client(settings.weather_timeout_seconds) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Weather fetch failed for (%s,%s): %s", latitude, longitude, exc)
        raise WeatherUnavailableError(
            "The weather service is unavailable right now. Weather auto-fill is "
            "off — you can still enter values manually."
        ) from exc
    except ValueError as exc:  # malformed JSON
        logger.warning("Weather response was not JSON: %s", exc)
        raise WeatherUnavailableError("The weather service returned an unreadable response.") from exc

    return payload


# ─────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────

def _sum(values: list[Any]) -> Optional[float]:
    numbers = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(numbers), 2) if numbers else None


def build_report(
    latitude: float,
    longitude: float,
    *,
    place_name: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch and normalise current weather + rainfall history/forecast.

    Returns a plain dict (validated by the response model in the router) that
    the frontend turns into form values. The three rainfall concepts live in
    separate keys so they can never be confused with one another.
    """
    payload = fetch_weather(latitude, longitude)
    settings = get_settings()

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    dates: list[str] = list(daily.get("time") or [])
    precip: list[Any] = list(daily.get("precipitation_sum") or [])
    rain: list[Any] = list(daily.get("rain_sum") or [])

    # "Today" in the location's own timezone (the API returns it in `current.time`).
    observed_at = current.get("time")
    today = (observed_at or "")[:10] or datetime.now(timezone.utc).date().isoformat()

    hist_dates, hist_precip, hist_rain = [], [], []
    fc_dates, fc_precip, fc_rain = [], [], []
    for i, day in enumerate(dates):
        p = precip[i] if i < len(precip) else None
        r = rain[i] if i < len(rain) else None
        if day < today:
            hist_dates.append(day); hist_precip.append(p); hist_rain.append(r)
        else:
            fc_dates.append(day); fc_precip.append(p); fc_rain.append(r)

    past_7 = [p for d, p in zip(hist_dates, hist_precip) if d >= _days_ago(today, 7)]

    temperature = current.get("temperature_2m")
    humidity = current.get("relative_humidity_2m")
    accumulated = _sum(hist_precip)

    autofill: dict[str, Any] = {}
    if isinstance(temperature, (int, float)):
        autofill["temperature"] = {
            "value": round(float(temperature), 1),
            "unit": "°C",
            "origin": "current observation",
            "label": "Current air temperature",
            "observed_at": observed_at,
            "is_cumulative": False,
        }
    if isinstance(humidity, (int, float)):
        autofill["humidity"] = {
            "value": round(float(humidity), 1),
            "unit": "%",
            "origin": "current observation",
            "label": "Current relative humidity",
            "observed_at": observed_at,
            "is_cumulative": False,
        }
    if accumulated is not None:
        autofill["rainfall"] = {
            "value": accumulated,
            "unit": "mm",
            "origin": "historical accumulation",
            "label": f"Accumulated rainfall — past {settings.weather_history_days} days",
            "observed_at": None,
            "is_cumulative": True,
            "note": _RAINFALL_AUTOFILL_NOTE.format(days=settings.weather_history_days),
        }

    return {
        "source": "Open-Meteo",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {
            "name": place_name,
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "timezone": timezone_name or payload.get("timezone"),
        },
        "current": {
            "observed_at": observed_at,
            "temperature_c": temperature,
            "humidity_pct": humidity,
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "label": "Current observation",
        },
        "forecast_rainfall": {
            "days": len(fc_dates),
            "total_mm": _sum(fc_precip),
            "daily": [
                {"date": d, "precipitation_mm": p, "rain_mm": r}
                for d, p, r in zip(fc_dates, fc_precip, fc_rain)
            ],
            "label": "Forecast rainfall (not yet fallen)",
        },
        "historical_rainfall": {
            "days": len(hist_dates),
            "past_7_days_mm": _sum(past_7),
            "total_mm": accumulated,
            "daily": [
                {"date": d, "precipitation_mm": p, "rain_mm": r}
                for d, p, r in zip(hist_dates, hist_precip, hist_rain)
            ],
            "label": "Historical rainfall (already fallen, cumulative)",
        },
        "autofill": autofill,
        "notes": [
            "Current conditions are today's observation; forecast rainfall is "
            "rain expected in the coming days; historical rainfall is rain that "
            "has already fallen. They are different quantities and are shown "
            "separately.",
            "Only temperature and humidity are auto-filled from the current "
            "observation. Rainfall is auto-filled from accumulated historical "
            "rainfall because the crop models were trained on cumulative "
            "seasonal rainfall.",
        ],
    }


def _days_ago(today: str, n: int) -> str:
    """ISO date ``n`` days before ``today`` (falls back to a sentinel string)."""
    try:
        return date.fromordinal(date.fromisoformat(today).toordinal() - n).isoformat()
    except ValueError:
        return "0000-00-00"
