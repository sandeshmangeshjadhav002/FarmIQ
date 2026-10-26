"""Demo-mode sensor simulator.

Generates readings that look like they came from a soil/weather probe node
(NPK, soil pH, temperature, humidity, soil moisture) so the whole ML pipeline can
be exercised without physical hardware — e.g. during a hackathon demo.

Hard rules baked into this module:

* Every reading is stamped ``is_demo: True`` and labelled ``"DEMO DATA"``. There
  is no code path that can produce a simulated reading without those markers,
  so simulated data can never be mistaken for a physical sensor.
* Value ranges are taken from the **same raw datasets the models were trained
  on** (via ``ml.validation.training_ranges``), not invented, so demo values are
  in-distribution and produce meaningful predictions.
* The payload is a superset of the real ingestion shape
  (``SensorReadingIn`` + NPK/pH/soil-moisture%). A real ESP32/ESP8266 device can
  POST the very same fields to ``/api/sensor-readings/ingest``; only the
  simulator sets ``is_demo``.
* Persistence is opt-in and always writes ``is_demo = true``. Real readings are
  never overwritten or mixed with demo rows.

Failure injection: pass ``fail`` (a list of channel names, or ``["all"]``) and
those channels come back as ``None`` with their names listed in
``failed_channels`` — a realistic "sensor went dark" case for testing.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ml import validation

logger = logging.getLogger("farmiq.simulator")

DEMO_LABEL = "DEMO DATA"

# Channels the simulator can produce. Each maps to the (domain, slot) whose
# real training range bounds it; ``None`` means the range comes from the
# documented device spec instead (see _FALLBACK_RANGES).
_CHANNELS: dict[str, tuple[Optional[str], Optional[str], str]] = {
    "nitrogen":        ("crop", "N", "kg/ha"),
    "phosphorous":     ("crop", "P", "kg/ha"),
    "potassium":       ("crop", "K", "kg/ha"),
    "ph":              ("crop", "ph", "pH"),
    "temperature":     ("crop", "temperature", "°C"),
    "humidity":        ("crop", "humidity", "%"),
    "soil_moisture":   ("irrigation", "soil_moisture", "raw ADC"),
    "soil_temperature":("irrigation", "soil_temperature", "°C"),
}

# Absolute bounds for channels the datasets do not cover, and sanity clamps.
# Capacitive soil-moisture probes report 0–2000 (dry–saturated); the percentage
# channel is derived from it against this documented full-scale value.
_MOISTURE_RAW_FULL_SCALE = 2000.0

# Physical plausibility clamps applied after sampling/overrides.
_CLAMPS: dict[str, tuple[float, float]] = {
    "ph": (0.0, 14.0),
    "humidity": (0.0, 100.0),
    "soil_moisture": (0.0, _MOISTURE_RAW_FULL_SCALE),
    "soil_moisture_pct": (0.0, 100.0),
    "temperature": (-20.0, 60.0),
    "soil_temperature": (-20.0, 60.0),
    "nitrogen": (0.0, 500.0),
    "phosphorous": (0.0, 500.0),
    "potassium": (0.0, 600.0),
}


def available_channels() -> list[str]:
    """Channel names in a stable order."""
    return [*_CHANNELS, "soil_moisture_pct"]


def channel_specs() -> dict[str, dict[str, Any]]:
    """Documented per-channel bounds + units (for GET /api/simulator/config)."""
    specs: dict[str, dict[str, Any]] = {}
    for channel, (domain, slot, unit) in _CHANNELS.items():
        low, high = _bounds(domain, slot)
        specs[channel] = {
            "unit": unit,
            "min": low,
            "max": high,
            "source": "dataset training range" if domain else "device spec",
        }
    specs["soil_moisture_pct"] = {
        "unit": "%",
        "min": 0.0,
        "max": 100.0,
        "source": f"derived from soil_moisture (full scale {int(_MOISTURE_RAW_FULL_SCALE)} ADC)",
    }
    return specs


def _bounds(domain: Optional[str], slot: Optional[str]) -> tuple[float, float]:
    """Real min/max for a channel, from the training data where available."""
    if domain and slot:
        stats = validation.training_ranges(domain).get(slot)
        if stats:
            return float(stats["min"]), float(stats["max"])
    # Only reachable if a raw dataset is missing; keeps the demo usable.
    return 0.0, 100.0


def generate(
    *,
    seed: Optional[int] = None,
    overrides: Optional[dict[str, float]] = None,
    fail: Optional[Iterable[str]] = None,
    noise: float = 0.0,
) -> dict[str, Any]:
    """Produce one DEMO reading.

    ``overrides`` sets exact channel values (configurable readings);
    ``fail`` lists channels to simulate as dead (``["all"]`` fails everything);
    ``noise`` adds ±noise fraction jitter (0 = deterministic given ``seed``).
    """
    rng = random.Random(seed)
    failures = {str(c) for c in (fail or [])}
    fail_all = "all" in failures
    overrides = overrides or {}

    reading: dict[str, float] = {}
    failed_channels: list[str] = []

    for channel in _CHANNELS:
        if fail_all or channel in failures:
            failed_channels.append(channel)
            continue
        if channel in overrides:
            value = float(overrides[channel])
        else:
            domain, slot, _ = _CHANNELS[channel]
            low, high = _bounds(domain, slot)
            value = rng.uniform(low, high)
            if noise:
                value *= 1 + rng.uniform(-noise, noise)
        reading[channel] = _clamp(channel, value)

    # Derived percentage channel (skipped if its source failed).
    pct_channel = "soil_moisture_pct"
    if fail_all or pct_channel in failures:
        failed_channels.append(pct_channel)
    elif pct_channel in overrides:
        reading[pct_channel] = _clamp(pct_channel, float(overrides[pct_channel]))
    elif "soil_moisture" in reading:
        reading[pct_channel] = _clamp(
            pct_channel, reading["soil_moisture"] / _MOISTURE_RAW_FULL_SCALE * 100.0
        )

    for channel in list(overrides):
        if channel not in reading and channel not in failed_channels:
            if fail_all or channel in failures:
                failed_channels.append(channel)
            else:
                reading[channel] = _clamp(channel, float(overrides[channel]))

    return {
        "is_demo": True,
        "label": DEMO_LABEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "reading": {k: round(v, 2) for k, v in reading.items()},
        "failed_channels": sorted(failed_channels),
        "notes": [
            f"All values are simulated {DEMO_LABEL} — they did not come from "
            "physical hardware.",
            "Value ranges follow the training datasets, so these readings are "
            "realistic but are not measurements of any real field.",
        ],
    }


def _clamp(channel: str, value: float) -> float:
    low, high = _CLAMPS.get(channel, (float("-inf"), float("inf")))
    return max(low, min(high, value))


def to_reading_row(simulated: dict[str, Any]) -> dict[str, Any]:
    """Map a simulated reading onto ``sensor_readings`` columns.

    Mirrors the real ingestion column names so demo and real rows are stored
    identically — the only difference is ``is_demo = true``.
    """
    reading = simulated["reading"]
    row: dict[str, Any] = {"is_demo": True}
    mapping = {
        "nitrogen": "nitrogen",
        "phosphorous": "phosphorous",
        "potassium": "potassium",
        "ph": "ph",
        "temperature": "temperature",
        "humidity": "humidity",
        "soil_temperature": "soil_temperature",
        "soil_moisture": "soil_moisture_raw",
        "soil_moisture_pct": "soil_moisture",
    }
    for channel, column in mapping.items():
        if channel in reading:
            row[column] = reading[channel]
    return row
