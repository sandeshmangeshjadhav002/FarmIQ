"""Input validation for the FarmIQ ML predictors.

Three distinct kinds of feedback are produced, and they are deliberately kept
separate so the frontend can treat them differently:

  * ``invalid``  – a value the engine cannot honestly process: not a number, or
    outside the *supported* range of the preprocessed pipeline
    (``FarmIQ-rag/src/preprocess_*.py`` ``VALID_RANGES``). These block the
    prediction (HTTP 422) instead of being silently clamped or dropped.
  * ``unusual``  – a value that is a real, permitted agricultural condition but
    lies **outside the range seen in the training data** (dataset min/max).
    Extrapolation warning only — the prediction still runs.
  * ``advisory`` – contextual notes, e.g. "being inside the training range does
    not guarantee a real-world-accurate prediction".

The training-data bounds are read from the *raw* (unscaled) datasets so they
reflect real units. ``datasets/processed/*.csv`` holds standardised values and
must never be used for this. Nothing here fabricates numbers: every bound is
computed from the datasets that ship with the repository.
"""
from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.errors import ModelNotAvailableError

logger = logging.getLogger("farmiq.ml.validation")

# ─────────────────────────────────────────────────────────────────────────
# Hard limits — mirror the preprocessing scripts' VALID_RANGES exactly.
# slot -> (min, max, unit)
# ─────────────────────────────────────────────────────────────────────────
SUPPORTED_RANGES: dict[str, dict[str, tuple[float, float, str]]] = {
    "crop": {
        "N": (0, 200, "kg/ha"),
        "P": (0, 200, "kg/ha"),
        "K": (0, 250, "kg/ha"),
        "temperature": (0, 55, "°C"),
        "humidity": (0, 100, "%"),
        "ph": (0, 14, "pH"),
        "rainfall": (0, 3000, "mm"),
    },
    "fertilizer": {
        "temparature": (0, 55, "°C"),
        "humidity": (0, 100, "%"),
        "moisture": (0, 100, "%"),
        "nitrogen": (0, 200, "kg/ha"),
        "potassium": (0, 250, "kg/ha"),
        "phosphorous": (0, 200, "kg/ha"),
    },
    "yield": {
        "crop_year": (1900, 2100, "year"),
        "area": (0, 1_000_000, "ha"),
        "annual_rainfall": (0, 10_000, "mm"),
        "fertilizer": (0, 100_000_000, "kg"),
        "pesticide": (0, 10_000_000, "kg"),
    },
    "irrigation": {
        "soil_moisture": (0, 2000, "raw ADC"),
        "soil_temperature": (0, 60, "°C"),
        "temperature": (0, 60, "°C"),
        "humidity": (0, 100, "%"),
        "crop_days": (0, 365, "days"),
    },
}

# Categorical slots per domain (validated against the fitted encoder).
CATEGORICAL_SLOTS: dict[str, tuple[str, ...]] = {
    "fertilizer": ("soil_type", "crop_type"),
    "yield": ("state_name", "season", "crop"),
    "irrigation": ("crop_type",),
}

# Human labels for the schema endpoint / messages.
FIELD_LABELS: dict[str, dict[str, str]] = {
    "crop": {"N": "Nitrogen (N)", "P": "Phosphorus (P)", "K": "Potassium (K)",
             "temperature": "Temperature", "humidity": "Humidity", "ph": "Soil pH",
             "rainfall": "Seasonal rainfall"},
    "fertilizer": {"temparature": "Temperature", "humidity": "Humidity",
                   "moisture": "Soil moisture", "nitrogen": "Nitrogen",
                   "potassium": "Potassium", "phosphorous": "Phosphorous",
                   "soil_type": "Soil type", "crop_type": "Crop type"},
    "yield": {"state_name": "State", "season": "Season", "crop": "Crop",
              "crop_year": "Crop year", "area": "Area",
              "annual_rainfall": "Annual rainfall", "fertilizer": "Fertilizer",
              "pesticide": "Pesticide"},
    "irrigation": {"soil_moisture": "Soil moisture", "soil_temperature": "Soil temperature",
                   "temperature": "Air temperature", "humidity": "Humidity",
                   "crop_days": "Days since planting", "crop_type": "Crop type"},
}

# Raw dataset column backing each numeric slot (mirrors ml/defaults.py).
_RAW_SOURCES: dict[str, tuple[str, str]] = {
    "crop": ("crop_recommendation", "Crop_recommendation.csv"),
    "fertilizer": ("fertilizer_recommendation", "Fertilizer Prediction.csv"),
    "yield": ("crop_yield_india", "crop_production.csv"),
    "irrigation": ("irrigation", "irrigation_dataset.csv"),
}

_NUMERIC_COLUMNS: dict[str, dict[str, str]] = {
    "crop": {"N": "N", "P": "P", "K": "K", "temperature": "temperature",
             "humidity": "humidity", "ph": "ph", "rainfall": "rainfall"},
    "fertilizer": {"temparature": "Temparature", "humidity": "Humidity",
                   "moisture": "Moisture", "nitrogen": "Nitrogen",
                   "potassium": "Potassium", "phosphorous": "Phosphorous"},
    "yield": {"crop_year": "Crop_Year", "area": "Area",
              "annual_rainfall": "Annual_Rainfall", "fertilizer": "Fertilizer",
              "pesticide": "Pesticide"},
    "irrigation": {"soil_moisture": "SoilMoisture", "soil_temperature": "SoilTemperature",
                   "temperature": "Temperature", "humidity": "Humidity",
                   "crop_days": "CropDays"},
}

# Every prediction is an interpolation/extrapolation of the training data; this
# sentence is surfaced with the results so a score is never read as a promise.
ACCURACY_DISCLAIMER = (
    "Being inside the model's training range does not guarantee an accurate "
    "real-world prediction. These models learn patterns from a limited public "
    "dataset and are a decision aid only — confirm important decisions with "
    "local soil testing and an agronomist."
)

_training_stats: dict[str, dict[str, dict[str, float]]] = {}


def _load_training_stats(domain: str) -> dict[str, dict[str, float]]:
    """Per-slot min/max observed in the raw training dataset (cached)."""
    if domain in _training_stats:
        return _training_stats[domain]

    subdir, filename = _RAW_SOURCES[domain]
    path: Path = get_settings().ml_raw_dir / subdir / filename
    if not path.exists():
        raise ModelNotAvailableError(
            f"Raw dataset for '{domain}' not found at {path}; input ranges "
            "cannot be derived from the training data."
        )

    columns = _NUMERIC_COLUMNS.get(domain, {})
    slot_by_column = {col: slot for slot, col in columns.items()}
    stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"min": float("inf"), "max": float("-inf")}
    )

    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            for column, slot in slot_by_column.items():
                raw = row.get(column)
                if raw in (None, ""):
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                entry = stats[slot]
                if value < entry["min"]:
                    entry["min"] = value
                if value > entry["max"]:
                    entry["max"] = value

    cleaned = {
        slot: {"min": entry["min"], "max": entry["max"]}
        for slot, entry in stats.items()
        if entry["min"] != float("inf")
    }
    logger.info("Derived '%s' training ranges from %s: %s", domain, path.name, cleaned)
    _training_stats[domain] = cleaned
    return cleaned


def training_ranges(domain: str) -> dict[str, dict[str, float]]:
    """Public accessor for the raw-dataset min/max per slot (cached).

    Used by the sensor simulator so DEMO readings are drawn from the same
    ranges the models were trained on (never from invented bounds). Returns an
    empty mapping when the raw dataset is unavailable.
    """
    try:
        return _load_training_stats(domain)
    except ModelNotAvailableError as exc:
        logger.warning("Training ranges unavailable for '%s': %s", domain, exc.detail)
        return {}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float) -> str:
    return f"{value:g}"


def validate(domain: str, values: dict[str, Any]) -> dict[str, Any]:
    """Validate one prediction payload against the real training data.

    Returns ``{"ok": bool, "invalid": [...], "unusual": [...], "advisory": [...]}``.
    ``ok`` is False only when at least one value is missing or unsupported.
    """
    if domain not in SUPPORTED_RANGES:
        raise ValueError(f"Unknown ML domain: {domain}")

    invalid: list[dict[str, Any]] = []
    unusual: list[dict[str, Any]] = []
    labels = FIELD_LABELS.get(domain, {})

    supported = SUPPORTED_RANGES[domain]
    try:
        training_stats = _load_training_stats(domain)
    except ModelNotAvailableError as exc:
        # Without the raw dataset we can still enforce the hard supported
        # ranges; only the "unusual vs training data" warning is unavailable.
        logger.warning("Training ranges unavailable for '%s': %s", domain, exc.detail)
        training_stats = {}

    for slot, (low, high, unit) in supported.items():
        label = labels.get(slot, slot)
        raw = values.get(slot)
        if raw is None or raw == "":
            invalid.append({
                "field": slot, "label": label, "value": None, "unit": unit,
                "kind": "missing",
                "message": f"{label} is required.",
            })
            continue
        number = _to_float(raw)
        if number is None:
            invalid.append({
                "field": slot, "label": label, "value": raw, "unit": unit,
                "kind": "not_a_number",
                "message": f"{label} must be a number.",
            })
            continue
        if number < low or number > high:
            invalid.append({
                "field": slot, "label": label, "value": number, "unit": unit,
                "kind": "out_of_supported_range",
                "supported_min": low, "supported_max": high,
                "message": (
                    f"{label} = {_fmt(number)} {unit} is outside the supported "
                    f"range {_fmt(low)}–{_fmt(high)} {unit} for this model. "
                    "The value was not changed — please correct it."
                ),
            })
            continue
        stats = training_stats.get(slot)
        if stats and (number < stats["min"] or number > stats["max"]):
            unusual.append({
                "field": slot, "label": label, "value": number, "unit": unit,
                "kind": "outside_training_range",
                "training_min": stats["min"], "training_max": stats["max"],
                "message": (
                    f"{label} = {_fmt(number)} {unit} is a valid value but falls "
                    f"outside the training data range ({_fmt(stats['min'])}–"
                    f"{_fmt(stats['max'])} {unit}). The prediction extrapolates "
                    "and may be less reliable."
                ),
            })

    # Categorical slots — warn (never block) on values the encoder has not seen.
    for slot in CATEGORICAL_SLOTS.get(domain, ()):
        label = labels.get(slot, slot)
        raw = values.get(slot)
        if raw is None or str(raw).strip() == "":
            invalid.append({
                "field": slot, "label": label, "value": None, "unit": None,
                "kind": "missing", "message": f"{label} is required.",
            })
            continue
        known = _known_categories(domain, slot)
        if known and str(raw).strip().title() not in {k.title() for k in known}:
            unusual.append({
                "field": slot, "label": label, "value": str(raw), "unit": None,
                "kind": "unknown_category",
                "message": (
                    f"{label} '{raw}' does not appear in the training data "
                    f"({', '.join(known[:6])}{'…' if len(known) > 6 else ''}). "
                    "The model will fall back to an 'unknown' category."
                ),
            })

    advisory = [ACCURACY_DISCLAIMER]
    return {
        "ok": not invalid,
        "invalid": invalid,
        "unusual": unusual,
        "advisory": advisory,
    }


def _known_categories(domain: str, slot: str) -> list[str]:
    """Allowed categorical values, from the fitted encoder (best effort)."""
    # Irrigation stores CropType as numeric codes (1=Paddy, 2=Ground Nuts); the
    # adapter translates the human names, so validate against the names the
    # farmer actually types rather than the internal codes.
    if domain == "irrigation" and slot == "crop_type":
        try:
            from ml.adapter import IRRIGATION_CROP_CODES
            return list(IRRIGATION_CROP_CODES.keys())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read irrigation crop codes: %s", exc)
            return []
    try:
        from ml.defaults import categorical_choices
        choices = categorical_choices(domain).get(slot)
        return [str(c) for c in choices] if choices else []
    except Exception as exc:  # noqa: BLE001 - a missing encoder must not break validation
        logger.warning("Could not read categories for %s.%s: %s", domain, slot, exc)
        return []


def schema(domain: str) -> dict[str, Any]:
    """Machine-readable ranges so the frontend can warn before submitting."""
    if domain not in SUPPORTED_RANGES:
        raise ValueError(f"Unknown ML domain: {domain}")
    labels = FIELD_LABELS.get(domain, {})
    try:
        training_stats = _load_training_stats(domain)
    except ModelNotAvailableError as exc:
        logger.warning("Training ranges unavailable for '%s': %s", domain, exc.detail)
        training_stats = {}
    fields: list[dict[str, Any]] = []
    for slot, (low, high, unit) in SUPPORTED_RANGES[domain].items():
        stats = training_stats.get(slot, {})
        fields.append({
            "field": slot,
            "label": labels.get(slot, slot),
            "type": "number",
            "unit": unit,
            "supported_min": low,
            "supported_max": high,
            "training_min": stats.get("min"),
            "training_max": stats.get("max"),
        })
    for slot in CATEGORICAL_SLOTS.get(domain, ()):
        fields.append({
            "field": slot,
            "label": labels.get(slot, slot),
            "type": "category",
            "options": _known_categories(domain, slot),
        })
    return {
        "domain": domain,
        "fields": fields,
        "advisory": ACCURACY_DISCLAIMER,
    }
