"""Input defaults for the voice assistant's ML calls.

When a farmer asks a prediction question without supplying every model input,
the assistant still runs the model. Missing values are taken, in priority
order, from:

  1. the latest **sensor reading** (real data from the farmer's own field),
  2. the farmer's **farm profile** (soil type, crop, area, location),
  3. the **mean / mode of the raw training dataset** that the model was fitted
     on (``FarmIQ-rag/datasets/raw``) — note that ``datasets/processed/*.csv``
     holds *scaled* values, so averages must never be taken from it,
  4. a documented **app default** for the few columns where a dataset average
     is meaningless (see ``_APP_DEFAULTS``).

Every filled value is returned with its source so the assistant can tell the
farmer exactly which numbers were assumed instead of inventing them silently.

Categorical values are validated against the fitted encoders' classes
(loaded from ``datasets/processed``), so a farm profile can never produce a
value the encoder would reject.
"""
from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from typing import Any, Optional

from app.config import get_settings
from app.errors import ModelNotAvailableError
from ml.adapter import IRRIGATION_CROP_CODES

logger = logging.getLogger("farmiq.ml.defaults")

# ── Where the raw (unscaled) training data lives ──────────────────────────
_RAW_FILES: dict[str, tuple[str, str]] = {
    "crop": ("crop_recommendation", "Crop_recommendation.csv"),
    "fertilizer": ("fertilizer_recommendation", "Fertilizer Prediction.csv"),
    "yield": ("crop_yield_india", "crop_production.csv"),
    "irrigation": ("irrigation", "irrigation_dataset.csv"),
}

# ── Fitted encoders, used to validate categorical defaults ────────────────
_ENCODERS: dict[str, tuple[str, str]] = {
    "fertilizer": ("fertilizer_recommendation", "categorical_encoder.joblib"),
    "yield": ("crop_yield_india", "categorical_encoder.joblib"),
    "irrigation": ("irrigation", "crop_encoder.joblib"),
}

# ── Slot name (voice_engine) -> raw dataset column ────────────────────────
# Numeric slots: filled with the dataset mean.
_NUMERIC_COLUMNS: dict[str, dict[str, str]] = {
    "crop": {"N": "N", "P": "P", "K": "K", "temperature": "temperature",
             "humidity": "humidity", "ph": "ph", "rainfall": "rainfall"},
    "fertilizer": {"temparature": "Temparature", "humidity": "Humidity",
                   "moisture": "Moisture", "nitrogen": "Nitrogen",
                   "potassium": "Potassium", "phosphorous": "Phosphorous"},
    "yield": {"crop_year": "Crop_Year", "annual_rainfall": "Annual_Rainfall"},
    "irrigation": {"soil_moisture": "SoilMoisture", "soil_temperature": "SoilTemperature",
                   "temperature": "Temperature", "humidity": "Humidity",
                   "crop_days": "CropDays"},
}

# Categorical slots: filled with the dataset mode. The order must match the
# encoder's ``categories_`` order below.
_CATEGORICAL_COLUMNS: dict[str, dict[str, str]] = {
    "fertilizer": {"soil_type": "Soil_Type", "crop_type": "Crop_Type"},
    "yield": {"state_name": "State", "season": "Season", "crop": "Crop"},
    "irrigation": {"crop_type": "CropType"},
}

# ── Sensor reading -> slot (real field data beats any average) ────────────
_SENSOR_COLUMNS: dict[str, dict[str, str]] = {
    "crop": {"temperature": "temperature", "humidity": "humidity"},
    "fertilizer": {"temparature": "temperature", "humidity": "humidity",
                   "moisture": "soil_moisture"},
    "irrigation": {"soil_moisture": "soil_moisture", "soil_temperature": "soil_temperature",
                   "temperature": "temperature", "humidity": "humidity"},
    "yield": {},
}

# App defaults for columns where the dataset average is not a per-farm value:
# Area/Fertilizer/Pesticide in crop_production.csv are district-year totals
# (means: ~180 000 ha, ~24 000 000 kg, ~48 000 kg), so the documented per-farm
# values used by the ML module form are applied instead.
_APP_DEFAULTS: dict[str, dict[str, float]] = {
    "yield": {"area": 1.0, "fertilizer": 50.0, "pesticide": 5.0},
}

# Free-text crop (farm profile) -> crop family.
_CROP_SYNONYMS: dict[str, str] = {
    "paddy": "Paddy", "rice": "Paddy", "धान": "Paddy", "तांदूळ": "Paddy",
    "wheat": "Wheat", "गहू": "Wheat",
    "maize": "Maize", "corn": "Maize", "मका": "Maize",
    "cotton": "Cotton", "कपास": "Cotton",
    "sugarcane": "Sugarcane", "ऊस": "Sugarcane",
    "groundnut": "Ground Nuts", "ground nut": "Ground Nuts", "groundnuts": "Ground Nuts",
    "भुईमूग": "Ground Nuts",
    "soybean": "Soyabean", "soya": "Soyabean", "soyabean": "Soyabean",
    "millets": "Millets", "bajra": "Bajra", "jowar": "Jowar", "ragi": "Ragi",
}

# Crop family -> exact label used by the yield dataset's encoder.
_YIELD_CROP_LABELS: dict[str, str] = {
    "Paddy": "Rice", "Cotton": "Cotton(lint)", "Ground Nuts": "Groundnut",
}

# Farm area units (the Farms form offers Acres / Hectares / Guntha) -> hectares.
_AREA_TO_HECTARE: dict[str, float] = {
    "acre": 0.4047, "acres": 0.4047,
    "hectare": 1.0, "hectares": 1.0, "ha": 1.0,
    "guntha": 0.0101,
}

_dataset_cache: dict[str, dict[str, Any]] = {}
_choices_cache: dict[str, dict[str, list[str]]] = {}


# ─────────────────────────────────────────────────────────────────────────
# Dataset averages (computed once per process)
# ─────────────────────────────────────────────────────────────────────────

def dataset_defaults(domain: str) -> dict[str, Any]:
    """Mean (numeric) / mode (categorical) per slot, from the raw training data."""
    if domain in _dataset_cache:
        return _dataset_cache[domain]

    subdir, filename = _RAW_FILES[domain]
    path = get_settings().ml_raw_dir / subdir / filename
    if not path.exists():
        raise ModelNotAvailableError(
            f"Raw dataset for '{domain}' not found at {path}. Inputs cannot be "
            "defaulted without it."
        )

    numeric = _NUMERIC_COLUMNS.get(domain, {})
    categorical = _CATEGORICAL_COLUMNS.get(domain, {})
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    freq: dict[str, Counter] = {slot: Counter() for slot in categorical}

    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            for slot, column in numeric.items():
                raw = row.get(column)
                if raw in (None, ""):
                    continue
                try:
                    sums[slot] += float(raw)
                except (TypeError, ValueError):
                    continue
                counts[slot] += 1
            for slot, column in categorical.items():
                raw = row.get(column)
                if raw not in (None, ""):
                    freq[slot][str(raw).strip()] += 1

    out: dict[str, Any] = {}
    for slot in numeric:
        if counts[slot]:
            out[slot] = round(sums[slot] / counts[slot], 4)
    for slot, counter in freq.items():
        if counter:
            out[slot] = counter.most_common(1)[0][0]

    logger.info("Computed '%s' dataset defaults from %s: %s", domain, path.name, out)
    _dataset_cache[domain] = out
    return out


def categorical_choices(domain: str) -> dict[str, list[str]]:
    """Slot -> allowed values, read from the fitted encoder's categories."""
    if domain in _choices_cache:
        return _choices_cache[domain]

    entry = _ENCODERS.get(domain)
    if not entry:
        _choices_cache[domain] = {}
        return {}
    subdir, filename = entry
    path = get_settings().ml_processed_dir / subdir / filename
    if not path.exists():
        raise ModelNotAvailableError(
            f"Encoder for '{domain}' not found at {path}. Categorical inputs "
            "cannot be validated without it."
        )
    import joblib

    encoder = joblib.load(path)
    if hasattr(encoder, "categories_"):
        groups = [[str(v).strip() for v in group] for group in encoder.categories_]
    else:  # LabelEncoder — a single column
        groups = [[str(v).strip() for v in encoder.classes_]]
    choices = {
        slot: groups[idx]
        for idx, slot in enumerate(_CATEGORICAL_COLUMNS[domain])
        if idx < len(groups)
    }
    _choices_cache[domain] = choices
    return choices


# ─────────────────────────────────────────────────────────────────────────
# Farm profile mapping
# ─────────────────────────────────────────────────────────────────────────

def _canonical_crop(domain: str, raw_crop: Any) -> Optional[str]:
    text = str(raw_crop or "").strip().lower()
    if not text:
        return None
    family = next(
        (name for key, name in _CROP_SYNONYMS.items() if key in text),
        None,
    )
    if not family:
        return None
    if domain == "irrigation":
        choices = categorical_choices(domain).get("crop_type") or []
        code = IRRIGATION_CROP_CODES.get(family)
        return code if code and code in choices else None
    slot = "crop" if domain == "yield" else "crop_type"
    choices = categorical_choices(domain).get(slot) or []
    label = _YIELD_CROP_LABELS.get(family, family) if domain == "yield" else family
    return label if label in choices else None


def _canonical_choice(domain: str, slot: str, raw_value: Any) -> Optional[str]:
    choices = categorical_choices(domain).get(slot) or []
    text = str(raw_value or "").strip()
    if not choices or not text:
        return None
    for choice in choices:
        if choice.lower() == text.lower():
            return choice
    return None


def _canonical_location(domain: str, raw_location: Any) -> Optional[str]:
    """Match a free-text farm location (e.g. "Nashik, Maharashtra") to a state."""
    choices = categorical_choices(domain).get("state_name") or []
    text = str(raw_location or "").strip().lower()
    if not choices or not text:
        return None
    for part in [p.strip() for p in text.split(",")]:
        for choice in choices:
            if choice.lower() == part:
                return choice
    for choice in choices:
        if choice.lower() in text:
            return choice
    return None


def _farm_area_hectares(farm: dict[str, Any]) -> Optional[float]:
    try:
        value = float(farm.get("area_value"))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    unit = str(farm.get("area_unit") or "hectares").strip().lower()
    factor = _AREA_TO_HECTARE.get(unit)
    if factor is None:                      # unknown unit — take the first hint
        factor = 0.4047 if "acre" in unit else 1.0 if "hect" in unit else None
    if factor is None:
        return None
    return round(value * factor, 4)


def _farm_values(domain: str, farm: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Slot values that can be derived from the farm profile."""
    if not farm:
        return {}
    if domain == "yield":
        values: dict[str, Any] = {}
        crop = _canonical_crop(domain, farm.get("current_crop"))
        state = _canonical_location(domain, farm.get("location"))
        area = _farm_area_hectares(farm)
        if crop:
            values["crop"] = crop
        if state:
            values["state_name"] = state
        if area:
            values["area"] = area
        return values
    if domain == "fertilizer":
        values = {}
        soil = _canonical_choice(domain, "soil_type", farm.get("soil_type"))
        crop = _canonical_crop(domain, farm.get("current_crop"))
        if soil:
            values["soil_type"] = soil
        if crop:
            values["crop_type"] = crop
        return values
    if domain == "irrigation":
        crop = _canonical_crop(domain, farm.get("current_crop"))
        return {"crop_type": crop} if crop else {}
    return {}


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def fill_missing_slots(
    domain: str,
    slots: dict[str, Any],
    missing: list[str],
    farm: Optional[dict[str, Any]] = None,
    latest_sensor: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fill ``missing`` slots in ``slots``.

    Returns ``(filled_slots, sources)`` where ``sources[slot]`` is a short
    human-readable label: "live sensor", "farm profile", "dataset average" or
    "app default". Slots that could not be filled are simply left out.
    """
    filled = dict(slots)
    sources: dict[str, str] = {}
    if not missing:
        return filled, sources

    sensor_columns = _SENSOR_COLUMNS.get(domain, {})
    farm_values = _farm_values(domain, farm)
    app_defaults = _APP_DEFAULTS.get(domain, {})
    defaults: Optional[dict[str, Any]] = None

    for slot in missing:
        sensor_key = sensor_columns.get(slot)
        if sensor_key and latest_sensor:
            sensor_value = latest_sensor.get(sensor_key)
            if sensor_value is not None:
                filled[slot] = float(sensor_value)
                sources[slot] = "live sensor"
                continue

        if slot in farm_values:
            filled[slot] = farm_values[slot]
            sources[slot] = "farm profile"
            continue

        if slot in app_defaults:
            filled[slot] = app_defaults[slot]
            sources[slot] = "app default"
            continue

        if defaults is None:
            defaults = dataset_defaults(domain)
        if slot in defaults:
            filled[slot] = defaults[slot]
            sources[slot] = "dataset average"

    return filled, sources
