"""Centralised farm data aggregator + context manager.

One place that gathers **everything FarmIQ already knows about a single farm**
and returns it as a structured, freshness-tagged dict. Every AI entry point
(the agent, the chat assistant, the event engine) reads its context from here
instead of hitting the database, the weather API and the ML store separately.

Reused, not duplicated
----------------------
* ``app.db``               — owner-scoped reads (the authorization layer).
* ``app.weather``          — Open-Meteo current + rainfall history/forecast.
* ``ml.adapter``           — which trained models / artefacts are available.
* ``app.ai_context``       — the field whitelist and the LLM-facing flattening.
* ``app.alerts_service``   — physical-plausibility bounds for readings.
* ``app.decision_engine``  — the staleness thresholds already in use.
* ``app.cache``            — short-lived weather + context caching.

Rules enforced here
-------------------
* **Whitelist only.** Only the fields declared below are copied. Coordinates,
  device tokens, owner ids and row ids never reach the output (the coordinates
  are used for the weather lookup and then dropped).
* **No fabrication.** A value appears only when the database or the API
  actually returned it. Nothing is inferred, averaged, rounded or defaulted;
  absent data is listed in ``missing`` instead.
* **Freshness is explicit.** Every section carries its own source, timestamp
  and a freshness verdict (fresh / stale / offline / missing).
* **Degrade, never raise.** A failure in one source (weather down, no sensors,
  cold ML adapter) blanks that section only — the call stays usable, because
  the agent must still answer when part of the farm data is unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app import db
from app import weather as weather_module
from app.ai_context import (
    FARM_FIELDS,
    READING_FIELDS,
    REQUIRED_READING_FIELDS,
    build_farm_context,
)
from app.alerts_service import (
    SENSOR_OFFLINE_AFTER_HOURS,
    SENSOR_STALE_AFTER_HOURS,
    invalid_channels,
)
from app.cache import TTLCache
from app.config import get_settings
from app.decision_engine import WEATHER_STALE_HOURS

logger = logging.getLogger("farmiq.context")

# ── Freshness verdicts ───────────────────────────────────────────────────────
FRESH = "fresh"
STALE = "stale"
OFFLINE = "offline"
MISSING = "missing"

# The reading channels the IoT engine is expected to report. Kept next to its
# DRY source (``ai_context.REQUIRED_READING_FIELDS``) so the completeness check
# has one definition — optional extras such as BME680 air pressure are
# forwarded as context but never flagged as missing.
SENSOR_CHANNELS = REQUIRED_READING_FIELDS

# Weather cache keyed by rounded coordinates. 3 decimals ≈ 110 m, close enough
# that two lookups for the same field share one report.
_WEATHER_CACHE: TTLCache = TTLCache(get_settings().weather_cache_ttl_seconds, maxsize=512)


def reset_caches() -> None:
    """Drop the cached weather reports (tests / after a config change)."""
    _WEATHER_CACHE.clear()


# ── Timestamp helpers ────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_hours(value: Any, now: datetime) -> Optional[float]:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return round((now - parsed).total_seconds() / 3600.0, 3)


def _sensor_freshness(age_hours: Optional[float]) -> str:
    if age_hours is None:
        return MISSING
    if age_hours >= SENSOR_OFFLINE_AFTER_HOURS:
        return OFFLINE
    if age_hours >= SENSOR_STALE_AFTER_HOURS:
        return STALE
    return FRESH


def _weather_freshness(age_hours: Optional[float]) -> str:
    if age_hours is None:
        return MISSING
    return STALE if age_hours >= WEATHER_STALE_HOURS else FRESH


# ── Section builders ─────────────────────────────────────────────────────────

def _load_farm(client: Any, owner_id: str, farm_id: Optional[str]) -> Optional[dict]:
    """The requested farm, else the owner's newest farm. Never raises."""
    try:
        if farm_id:
            return db.get_farm(client, owner_id, farm_id)
        farms, _ = db.list_farms(client, owner_id, limit=1, offset=0)
        return farms[0] if farms else None
    except Exception as exc:  # noqa: BLE001 — best-effort context only
        logger.warning("Could not load farm for user %s: %s", owner_id, exc)
        return None


def _farm_section(farm: Optional[dict]) -> Optional[dict]:
    if not farm:
        return None
    fields = {key: farm[key] for key in FARM_FIELDS if farm.get(key) not in (None, "")}
    if not fields:
        return None
    # ``id`` links the section back to the farm row for tools; it is dropped
    # from the LLM-facing flattening below.
    fields["id"] = farm.get("id")
    return {
        **fields,
        "meta": {"source": "farms", "as_of": farm.get("created_at"), "recorded": True},
    }


def _sensor_section(
    client: Any, owner_id: str, farm: Optional[dict], now: datetime
) -> tuple[Optional[dict], Optional[dict]]:
    """Latest reading (any source) + a compact device summary. Never raises."""
    reading: Optional[dict] = None
    try:
        rows, _ = db.list_sensor_readings(
            client, owner_id, farm_id=(farm or {}).get("id"), limit=1, offset=0
        )
        reading = rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load sensor readings for user %s: %s", owner_id, exc)

    devices_summary: Optional[dict] = None
    try:
        devices, total = db.list_devices(client, owner_id, limit=100, offset=0)
        devices_summary = {
            "count": total,
            "online": sum(1 for d in devices if d.get("is_online")),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load devices for user %s: %s", owner_id, exc)

    if not reading:
        return None, devices_summary

    # Every known channel the row actually carries is forwarded (including
    # optional extras such as BME680 air pressure); completeness is judged only
    # against the channels a standard probe is expected to report.
    present = {ch: reading[ch] for ch in READING_FIELDS if reading.get(ch) not in (None, "")}
    absent = [ch for ch in SENSOR_CHANNELS if ch not in present]
    age = _age_hours(reading.get("created_at"), now)

    section = {
        **present,
        "device_id": reading.get("device_id"),
        "is_demo": bool(reading.get("is_demo")),
        "observed_at": reading.get("created_at"),
        "age_hours": age,
        "freshness": _sensor_freshness(age),
        # Channels the probe reported but that fall outside physical bounds —
        # a data-quality signal, surfaced rather than silently ignored.
        "invalid_channels": invalid_channels(reading),
        "missing_channels": absent,
        "devices": devices_summary,
        "meta": {
            "source": "demo_simulator" if reading.get("is_demo") else "device",
            "as_of": reading.get("created_at"),
            "recorded": True,
        },
    }
    return section, devices_summary


def weather_report(
    farm: Optional[dict],
    now: Optional[datetime] = None,
    weather_fetcher: Optional[Callable[..., dict]] = None,
) -> Optional[dict]:
    """The raw (cached) weather report for ``farm``, or ``None`` when unavailable.

    Public because consumers that need the *full* report shape — the decision
    engine's 48-hour rainfall forecast, for instance — must share one cached
    network call instead of duplicating the fetch here.
    """
    if not farm:
        return None

    fetch = weather_fetcher or weather_module.build_report
    latitude, longitude = farm.get("latitude"), farm.get("longitude")
    place = farm.get("location")

    def _fetch() -> Optional[dict]:
        try:
            if latitude is not None and longitude is not None:
                return fetch(float(latitude), float(longitude), place_name=place)
            if place:
                geo = weather_module.geocode(place)
                return fetch(geo["latitude"], geo["longitude"], place_name=geo.get("name"))
        except Exception as exc:  # noqa: BLE001 — weather is optional
            logger.info("Weather unavailable for farm context: %s", type(exc).__name__)
        return None

    key: Optional[tuple] = None
    if latitude is not None and longitude is not None:
        key = ("coords", round(float(latitude), 3), round(float(longitude), 3))
    elif place:
        key = ("place", str(place).strip().lower())

    return _WEATHER_CACHE.get_or_set(key, _fetch) if key else _fetch()


def _weather_section(
    farm: Optional[dict],
    now: datetime,
    weather_fetcher: Callable[..., dict],
) -> tuple[Optional[dict], list[str]]:
    """Current weather + rainfall totals for the farm. Returns (section, warnings)."""
    if not farm:
        return None, []

    report = weather_report(farm, now, weather_fetcher)
    if not report:
        return None, ["weather_unavailable"]

    current = report.get("current") or {}
    forecast = report.get("forecast_rainfall") or {}
    historical = report.get("historical_rainfall") or {}
    observed_at = current.get("observed_at")
    age = _age_hours(observed_at, now)

    section = {
        "temperature_c": current.get("temperature_c"),
        "humidity_pct": current.get("humidity_pct"),
        "precipitation_mm": current.get("precipitation_mm"),
        "forecast_rain_7d_mm": forecast.get("total_mm"),
        "historical_rain_30d_mm": historical.get("total_mm"),
        "observed_at": observed_at,
        "fetched_at": report.get("fetched_at"),
        "age_hours": age,
        "freshness": _weather_freshness(age),
        "location": (report.get("location") or {}).get("name"),
        "meta": {
            "source": report.get("source"),
            "as_of": report.get("fetched_at"),
            "recorded": True,
        },
    }
    return section, []


def _ml_section(client: Any, owner_id: str, now: datetime) -> dict:
    """Latest stored prediction per domain + which trained models are loaded."""
    latest: dict[str, dict] = {}
    try:
        rows, _ = db.list_predictions(client, owner_id, limit=50, offset=0)
        for row in rows:  # already newest-first
            domain = row.get("domain")
            if domain and domain not in latest:
                latest[domain] = {
                    "prediction": (row.get("output") or {}).get("prediction"),
                    "label": (row.get("output") or {}).get("label"),
                    "source": row.get("source"),
                    "input": row.get("input"),
                    "created_at": row.get("created_at"),
                    "age_hours": _age_hours(row.get("created_at"), now),
                    "meta": {"source": "predictions", "as_of": row.get("created_at"), "recorded": True},
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load prediction history for user %s: %s", owner_id, exc)

    models: dict[str, Any] = {}
    try:
        from ml.adapter import get_adapter

        models = get_adapter().status()
    except Exception as exc:  # noqa: BLE001 — availability is informative only
        logger.info("ML adapter status unavailable: %s", type(exc).__name__)

    return {"latest": latest, "models": models}


# ── Entry point ──────────────────────────────────────────────────────────────

def build_context(
    client: Any,
    owner_id: str,
    *,
    farm_id: Optional[str] = None,
    include_weather: bool = True,
    weather_fetcher: Optional[Callable[..., dict]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the structured context for one farm, owned by ``owner_id``.

    ``farm_id`` selects a specific farm; omitted, the newest farm is used.
    ``include_weather`` lets a caller skip the (network) weather lookup.
    ``weather_fetcher`` is injectable for tests; it defaults to
    :func:`app.weather.build_report`.
    """
    now = now or datetime.now(timezone.utc)
    fetch = weather_fetcher or weather_module.build_report

    context: dict[str, Any] = {
        "owner_id": owner_id,
        "generated_at": now.isoformat(),
        "farm": None,
        "profile": None,
        "sensors": None,
        "weather": None,
        "ml": {"latest": {}, "models": {}},
        "llm_context": None,
        "missing": [],
        "warnings": [],
    }

    # Farmer profile — role only. Names, emails and mobiles are never copied.
    try:
        profile = db.get_profile(client, owner_id)
        context["profile"] = {
            "role": profile.get("role"),
            "meta": {"source": "profiles", "as_of": profile.get("created_at"), "recorded": True},
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load profile for user %s: %s", owner_id, exc)

    farm = _load_farm(client, owner_id, farm_id)
    farm_section = _farm_section(farm)
    context["farm"] = farm_section

    sensor_section, _ = _sensor_section(client, owner_id, farm, now)
    context["sensors"] = sensor_section

    if include_weather:
        weather_section, weather_warnings = _weather_section(farm, now, fetch)
        context["weather"] = weather_section
        context["warnings"].extend(weather_warnings)

    context["ml"] = _ml_section(client, owner_id, now)

    # The LLM-facing flattening reuses the single, audited definition in
    # ai_context so the assistant's prompt dialect stays identical everywhere.
    reading = None
    if sensor_section:
        reading = {**sensor_section, "created_at": sensor_section.get("observed_at")}
    context["llm_context"] = build_farm_context(farm, reading)

    context["missing"] = _collect_missing(context)
    return context


def _collect_missing(context: dict[str, Any]) -> list[str]:
    """Human-readable list of what is absent, so the agent can say so honestly."""
    missing: list[str] = []
    if not context.get("farm"):
        missing.append("farm_profile")
    sensors = context.get("sensors")
    if not sensors:
        missing.append("sensor_readings")
    else:
        if sensors.get("freshness") in (STALE, OFFLINE):
            missing.append(f"sensor_readings ({sensors['freshness']})")
        for channel in sensors.get("missing_channels", []):
            missing.append(f"sensor:{channel}")
    if context.get("weather") is None:
        missing.append("weather")
    for domain in ("crop", "fertilizer", "yield", "irrigation"):
        if domain not in (context.get("ml", {}).get("latest") or {}):
            missing.append(f"prediction:{domain}")
    return missing


def to_prompt_context(context: dict[str, Any]) -> Optional[dict]:
    """Flatten a context into the ``farm_context`` shape the RAG prompt expects.

    Returns the same keys :func:`app.ai_context.build_farm_context` produces
    (farm + latest reading), enriched with the live weather summary. Returns
    ``None`` when there is nothing real to share, so the caller can pass it
    straight through and leave the prompt unchanged.
    """
    flat: dict[str, Any] = dict(context.get("llm_context") or {})

    weather = context.get("weather") or {}
    weather_map = {
        "weather_temperature_c": weather.get("temperature_c"),
        "weather_humidity_pct": weather.get("humidity_pct"),
        "weather_forecast_rain_7d_mm": weather.get("forecast_rain_7d_mm"),
        "weather_observed_at": weather.get("observed_at"),
    }
    for key, value in weather_map.items():
        if value not in (None, ""):
            flat[key] = value

    return flat or None


# ── Public section accessors ─────────────────────────────────────────────────
# The agent's tools fetch one section at a time, so a question about the weather
# never also reads the sensor history. These thin wrappers expose the builders
# above; ``build_context`` keeps its current behaviour and output unchanged.

def load_farm(
    client: Any, owner_id: str, farm_id: Optional[str] = None
) -> Optional[dict]:
    """The requested farm row, else the owner's newest farm (or ``None``)."""
    return _load_farm(client, owner_id, farm_id)


def farm_section(farm: Optional[dict]) -> Optional[dict]:
    """Whitelisted farm fields plus provenance, or ``None`` when empty."""
    return _farm_section(farm)


def sensor_section(
    client: Any,
    owner_id: str,
    farm: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Latest reading (any source), freshness verdicts and device summary."""
    section, _ = _sensor_section(client, owner_id, farm, now or datetime.now(timezone.utc))
    return section


def weather_section(
    farm: Optional[dict],
    now: Optional[datetime] = None,
    weather_fetcher: Optional[Callable[..., dict]] = None,
) -> tuple[Optional[dict], list[str]]:
    """Current weather + rainfall totals. Returns ``(section, warnings)``."""
    return _weather_section(farm, now or datetime.now(timezone.utc), weather_fetcher)


def ml_section(
    client: Any, owner_id: str, now: Optional[datetime] = None
) -> dict:
    """Latest stored prediction per domain + loaded-model availability."""
    return _ml_section(client, owner_id, now or datetime.now(timezone.utc))
