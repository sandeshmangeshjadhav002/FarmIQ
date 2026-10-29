"""Deterministic alert rules for the Alerts & Notifications module.

Everything in this module is a **pure function of a plain dict** — no database,
no network, no request context — so every rule can be unit-tested directly and
the same input always produces the same alerts.

Contract
--------
``derive_alerts(context, now)`` returns a list of alert drafts. Each draft has::

    kind, priority, title, body, reason, subject_id, dedup_key, is_demo

The router (``app/routers/alerts.py``) assembles ``context`` from the account's
stored data and ``app/db.py`` persists whatever this module returns.

Hard rules baked in here
------------------------
* **No alert without data.** Each rule first checks that the data it describes
  exists (and, for time-based rules, that a timestamp exists). A brand-new
  account with no devices, readings or assessments yields ``[]`` — never a
  placeholder or "sample" alert.
* **No fabricated values.** Titles/bodies only restate numbers that were passed
  in; nothing is estimated, rounded-up or invented.
* **Stable dedup keys.** Re-running a refresh updates the existing alert rather
  than creating a duplicate, so the list cannot accumulate repeats.
* **Demo data stays marked.** An alert raised from a simulated reading carries
  ``is_demo=True`` so it is never mistaken for a hardware event.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# ── Thresholds ────────────────────────────────────────────────────────────
# A device that has not reported for this long is treated as disconnected.
# 6 h is deliberately generous: a soil probe on a solar/battery node typically
# reports every 15–60 min, so a 6 h gap means something is wrong.
SENSOR_OFFLINE_AFTER_HOURS = 6.0
# Between "fresh" and the offline threshold the reading is present but stale.
SENSOR_STALE_AFTER_HOURS = 1.0
# Forecast rain (next 7 days) at or above this is worth an advance warning.
HEAVY_RAIN_FORECAST_MM = 50.0
# Reported historical rainfall below this, when weather was actually fetched.
LOW_RAINFALL_MM = 10.0

# Drought severities that warrant an alert, and the priority they map to.
DROUGHT_PRIORITY: dict[str, str] = {"extreme": "critical", "severe": "high"}

PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Physical plausibility bounds. Mirrors app/simulator.py's clamps and the
# documented device spec — a value outside these cannot have come from a
# working probe, so it is a data-quality problem worth surfacing.
PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "ph": (0.0, 14.0),
    "humidity": (0.0, 100.0),
    "soil_moisture": (0.0, 2000.0),
    "soil_moisture_raw": (0.0, 2000.0),
    "soil_temperature": (-20.0, 60.0),
    "temperature": (-20.0, 60.0),
    "nitrogen": (0.0, 500.0),
    "phosphorous": (0.0, 500.0),
    "potassium": (0.0, 600.0),
}


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return None when absent or unparseable."""
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
    """Hours elapsed since ``value``; None when the timestamp is missing."""
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 3600.0


def invalid_channels(reading: dict[str, Any]) -> list[str]:
    """Channels in ``reading`` whose value is outside physical bounds."""
    bad: list[str] = []
    for channel, (low, high) in PHYSICAL_BOUNDS.items():
        value = reading.get(channel)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            bad.append(channel)
            continue
        if number < low or number > high:
            bad.append(channel)
    return sorted(bad)


def _draft(
    *,
    kind: str,
    priority: str,
    title: str,
    body: str,
    reason: str,
    dedup_key: str,
    subject_id: Optional[str] = None,
    is_demo: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "priority": priority,
        "title": title,
        "body": body,
        "reason": reason,
        "subject_id": subject_id,
        "dedup_key": dedup_key,
        "is_demo": is_demo,
    }


def _fmt_hours(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


# ── Rules ─────────────────────────────────────────────────────────────────

def _sensor_alerts(context: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Device connectivity (offline / stale) and reading plausibility."""
    alerts: list[dict[str, Any]] = []
    devices = context.get("devices") or []
    readings = context.get("latest_reading_by_device") or {}

    for device in devices:
        device_id = device.get("id")
        if not device_id:
            continue
        name = device.get("name") or "Sensor"
        reading = readings.get(device_id) or {}
        is_demo = bool(reading.get("is_demo"))
        age = _age_hours(device.get("last_seen_at"), now)
        explicitly_offline = device.get("is_online") is False

        if explicitly_offline or (age is not None and age >= SENSOR_OFFLINE_AFTER_HOURS):
            detail = (
                "no data has ever been received"
                if age is None
                else f"last contact was {_fmt_hours(age)} ago"
            )
            alerts.append(_draft(
                kind="sensor",
                priority="high",
                title=f"{name} has stopped reporting",
                body=f"This sensor is not sending readings — {detail}.",
                reason=(
                    f"Device contact age {'is unknown' if age is None else _fmt_hours(age)} "
                    f"(offline threshold {SENSOR_OFFLINE_AFTER_HOURS:.0f} h)."
                ),
                dedup_key=f"sensor_offline:{device_id}",
                subject_id=device_id,
                is_demo=is_demo,
            ))
        elif age is not None and age >= SENSOR_STALE_AFTER_HOURS:
            alerts.append(_draft(
                kind="sensor",
                priority="medium",
                title=f"{name} readings may be stale",
                body=f"The last reading from this sensor arrived {_fmt_hours(age)} ago.",
                reason=(
                    f"Device contact age {_fmt_hours(age)} "
                    f"(stale threshold {SENSOR_STALE_AFTER_HOURS:.0f} h)."
                ),
                dedup_key=f"sensor_stale:{device_id}",
                subject_id=device_id,
                is_demo=is_demo,
            ))
        # age is None with a paired device: no contact recorded yet -> nothing
        # to assert, so no alert (never warn on missing data).

        if reading:
            bad = invalid_channels(reading)
            if bad:
                alerts.append(_draft(
                    kind="sensor",
                    priority="medium",
                    title=f"{name} reported implausible values",
                    body=(
                        "These channels are outside the physically possible range "
                        f"and should be checked: {', '.join(bad)}."
                    ),
                    reason=(
                        "Values outside documented sensor bounds (see PHYSICAL_BOUNDS) "
                        "usually mean a faulty probe or a bad calibration."
                    ),
                    dedup_key=f"sensor_invalid:{device_id}",
                    subject_id=device_id,
                    is_demo=is_demo,
                ))

    return alerts


def _irrigation_alerts(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Drought severity from the most recent saved assessment."""
    assessment = context.get("latest_assessment")
    if not assessment:
        return []

    severity = assessment.get("drought_severity")
    priority = DROUGHT_PRIORITY.get(severity or "")
    if not priority:
        return []

    assessment_id = assessment.get("id") or "latest"
    crop = assessment.get("crop") or "your crop"
    reason_text = assessment.get("drought_severity_reason") or ""
    return [_draft(
        kind="irrigation",
        priority=priority,
        title=f"{severity.title()} drought conditions for {crop}",
        body="Review the irrigation and water-conservation plan for this farm.",
        reason=reason_text or f"Latest saved drought assessment reported '{severity}' severity.",
        dedup_key=f"irrigation:{assessment_id}",
        subject_id=assessment_id,
    )]


def _weather_alerts(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Weather risk from a drought assessment's *fetched* weather snapshot.

    Only fires when the assessment actually carried a live snapshot
    (``fetched`` true) — an unavailable forecast produces no alert.
    """
    assessment = context.get("latest_assessment")
    if not assessment:
        return []

    weather = assessment.get("weather") or {}
    if not weather.get("fetched"):
        return []

    assessment_id = assessment.get("id") or "latest"
    location = assessment.get("location") or "your farm"

    forecast = weather.get("forecast_rain_7d_mm")
    if forecast is not None and float(forecast) >= HEAVY_RAIN_FORECAST_MM:
        return [_draft(
            kind="weather",
            priority="high",
            title=f"Heavy rain forecast near {location}",
            body=(
                f"About {float(forecast):.0f} mm of rain is forecast over the next 7 days. "
                "Delay irrigation and check field drainage."
            ),
            reason=(
                f"Open-Meteo 7-day forecast total {float(forecast):.0f} mm "
                f"(threshold {HEAVY_RAIN_FORECAST_MM:.0f} mm). Forecast rain has not fallen yet."
            ),
            dedup_key=f"weather_rain:{assessment_id}",
            subject_id=assessment_id,
        )]

    historical = weather.get("historical_rain_mm")
    if historical is not None and float(historical) < LOW_RAINFALL_MM:
        days = weather.get("historical_days")
        window = f"the last {days} days" if days else "the recent period"
        return [_draft(
            kind="weather",
            priority="medium",
            title=f"Very little rain recorded near {location}",
            body=(
                f"Only {float(historical):.0f} mm was recorded over {window}. "
                "Plan irrigation and moisture conservation."
            ),
            reason=(
                f"Open-Meteo recorded {float(historical):.0f} mm over {window} "
                f"(low threshold {LOW_RAINFALL_MM:.0f} mm)."
            ),
            dedup_key=f"weather_dry:{assessment_id}",
            subject_id=assessment_id,
        )]

    return []


def _prediction_alerts(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Flag predictions that fell back to the documented rule-based baseline.

    ``source == "baseline"`` means the trained model was not available and a
    documented rule was used instead (see ml/adapter.py). That is real,
    recorded information — not a guess.
    """
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for prediction in context.get("latest_predictions") or []:
        output = prediction.get("output") or {}
        if output.get("source") != "baseline":
            continue
        domain = prediction.get("domain") or "unknown"
        if domain in seen:
            continue
        seen.add(domain)
        alerts.append(_draft(
            kind="prediction",
            priority="low",
            title=f"{domain.title()} prediction used a baseline rule",
            body=(
                "The trained model was unavailable, so a documented rule-based "
                "baseline produced this result. Treat it as guidance, not a model output."
            ),
            reason=(
                f"Stored prediction recorded source='baseline' for the '{domain}' domain, "
                "which means no trained model was loaded at that time."
            ),
            dedup_key=f"prediction_baseline:{domain}",
            subject_id=domain,
        ))
    return alerts


# ── Entry point ───────────────────────────────────────────────────────────

def derive_alerts(
    context: dict[str, Any], now: Optional[datetime] = None
) -> list[dict[str, Any]]:
    """Run every rule and return the alert drafts, highest priority first.

    ``context`` keys (all optional — missing keys simply disable their rules):

    ``devices``                 list of ``devices`` rows for the owner
    ``latest_reading_by_device`` ``{device_id: sensor_readings row}``
    ``latest_assessment``       most recent saved drought assessment (full row)
    ``latest_predictions``      recent ``predictions`` rows for the owner
    """
    now = now or datetime.now(timezone.utc)

    drafts: list[dict[str, Any]] = []
    drafts.extend(_sensor_alerts(context, now))
    drafts.extend(_irrigation_alerts(context))
    drafts.extend(_weather_alerts(context))
    drafts.extend(_prediction_alerts(context))

    drafts.sort(key=lambda a: (PRIORITY_ORDER.get(a["priority"], 4), a["title"]))
    return drafts
