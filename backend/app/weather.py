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
import threading
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

# A pooled client per timeout value. The previous implementation constructed a
# new ``httpx.Client`` for every lookup, which meant a full DNS resolve + TCP +
# TLS handshake to Open-Meteo on every prediction-form auto-fill. httpx clients
# are thread-safe, so the pooled client is shared across the request threadpool.
_clients: dict[float, httpx.Client] = {}
_clients_lock = threading.Lock()


def _client(timeout: float) -> httpx.Client:
    """Shared, connection-pooled HTTP client for the weather providers.

    Callers must NOT use this as a context manager: exiting an ``httpx.Client``
    context closes it, which would kill the pool for every later request.
    """
    client = _clients.get(timeout)
    if client is None:
        with _clients_lock:
            client = _clients.get(timeout)
            if client is None:
                client = httpx.Client(timeout=timeout, headers={"User-Agent": "FarmIQ/2.0"})
                _clients[timeout] = client
    return client


def close_clients() -> None:
    """Close every pooled client (called from the app shutdown hook)."""
    with _clients_lock:
        for client in _clients.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
        _clients.clear()


def geocode(location: str) -> dict[str, Any]:
    """Resolve a place name to coordinates via the Open-Meteo geocoding API."""
    settings = get_settings()
    url = f"{settings.weather_geocoding_url.rstrip('/')}/search"
    params = {"name": location, "count": 1, "language": "en", "format": "json"}
    try:
        resp = _client(settings.weather_timeout_seconds).get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Geocoding failed for '%s': %s", location, type(exc).__name__)
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


def _place_label(props: dict[str, Any]) -> str:
    """Build a short "village, district, state, country" label from Photon props.

    Photon returns a flat property bag whose keys depend on what OpenStreetMap
    knows about the point. A farm is usually near a settlement, so the
    settlement name is preferred, then the administrative area. Duplicates are
    dropped (a village and its district often share a name) and the label is
    capped at four parts so it stays readable in a form field.
    """
    candidates = [
        props.get("name") or props.get("locality"),
        props.get("district") or props.get("city") or props.get("county"),
        props.get("state"),
        props.get("country"),
    ]
    parts: list[str] = []
    for value in candidates:
        text = str(value).strip() if value else ""
        if text and text.lower() not in {p.lower() for p in parts}:
            parts.append(text)
    return ", ".join(parts)


def reverse_geocode(latitude: float, longitude: float) -> dict[str, Any]:
    """Resolve coordinates to a human-readable place label via Photon.

    Used to *pre-fill* the farm's location field after the device supplies a
    GPS fix. The coordinates remain the authoritative value — this label is a
    convenience the farmer can edit, so a wrong or vague result is harmless.

    Photon is key-less but not anonymous: its usage policy asks clients to
    identify themselves, which ``_client`` does via the User-Agent header.
    """
    settings = get_settings()
    url = f"{settings.weather_reverse_url.rstrip('/')}/reverse"
    params = {"lat": latitude, "lon": longitude, "limit": 1, "lang": "en"}
    try:
        resp = _client(settings.weather_timeout_seconds).get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Reverse geocoding failed for (%s,%s): %s", latitude, longitude, type(exc).__name__)
        raise WeatherUnavailableError(
            "Could not look up a place name for these coordinates. You can type "
            "the location name yourself — the coordinates are still saved."
        ) from exc
    except ValueError as exc:  # malformed JSON
        logger.warning("Reverse geocode response was not JSON: %s", exc)
        raise WeatherUnavailableError(
            "The location service returned an unreadable response."
        ) from exc

    features = payload.get("features") or []
    if not features:
        raise AppError(404, "No place name could be found for these coordinates.")
    props = features[0].get("properties") or {}
    label = _place_label(props)
    if not label:
        raise AppError(404, "No place name could be found for these coordinates.")

    return {
        "label": label,
        "village": props.get("locality") or props.get("district") or props.get("city"),
        "district": props.get("district") or props.get("county"),
        "state": props.get("state"),
        "country": props.get("country"),
        "postcode": props.get("postcode"),
        "latitude": latitude,
        "longitude": longitude,
        "source": "Photon (OpenStreetMap contributors, ODbL)",
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
        resp = _client(settings.weather_timeout_seconds).get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Weather fetch failed for (%s,%s): %s", latitude, longitude, type(exc).__name__)
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
