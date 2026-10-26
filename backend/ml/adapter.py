"""ML adapter for FarmIQ.

This service layer wraps the **existing** preprocessing artefacts produced by
FarmIQ-rag/src/preprocess_*.py (scalers, encoders, feature metadata, label
maps). It applies the *exact* feature order and preprocessing those scripts
used, then calls a trained model **if a model file is present**.

Per the project requirements:
  * No predictions are fabricated or hardcoded.
  * If a trained model file is absent, the endpoint returns HTTP 501
    (ModelNotAvailable), EXCEPT irrigation which falls back to the existing
    rule-based baseline documented in rule_based_baseline.json.
  * Models are NOT retrained here. Run ``python -m ml.train_models`` to train
    real models from the existing preprocessed datasets (optional, opt-in).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import ModelNotAvailableError

logger = logging.getLogger("farmiq.ml")

# Domain key -> processed subdirectory name under FarmIQ-rag/datasets/processed
DOMAIN_DIRS = {
    "crop": "crop_recommendation",
    "fertilizer": "fertilizer_recommendation",
    "yield": "crop_yield_india",
    "irrigation": "irrigation",
}

# Exact numeric feature orders (from preprocess_*.py + feature_meta.json)
CROP_NUMERIC = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
FERT_NUMERIC = ["Temparature", "Humidity", "Moisture", "Nitrogen", "Potassium", "Phosphorous"]
FERT_CATEGORICAL = ["Soil Type", "Crop Type"]
YIELD_CATEGORICAL = ["State_Name", "Season", "Crop"]
YIELD_NUMERIC = ["Crop_Year", "Area", "Annual_Rainfall", "Fertilizer", "Pesticide"]
IRR_NUMERIC = ["SoilMoisture", "SoilTemperature", "Temperature", "Humidity", "CropDays"]

# Irrigation dataset crop-code legend (see FarmIQ-rag/datasets/README.md):
# the GCEKIoT dataset stores CropType as numeric codes, where Paddy = 1 and
# Ground Nuts = 2. The LabelEncoder was fit on these string codes, so crop
# names sent by the frontend must be translated before encoding.
IRRIGATION_CROP_CODES = {"Paddy": "1", "Ground Nuts": "2"}


def _resolve_irrigation_crop(crop: Any, classes: list[str]) -> str:
    """Translate a crop_type from a request into a LabelEncoder class.

    Accepts either the raw dataset code (e.g. ``"1"``) or a crop name
    (e.g. ``"Paddy"``). Unknown values fall back to the encoder's first class,
    matching the training-time handling of unseen crop types.
    """
    name = str(crop or "Paddy").strip()
    if name in classes:
        return name
    for crop_name, code in IRRIGATION_CROP_CODES.items():
        if crop_name.lower() == name.lower() and code in classes:
            return code
    return classes[0]


def _load_joblib(path: Path):
    import joblib
    return joblib.load(path)


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class MLAdapter:
    """Loads preprocessing artefacts and (optionally) trained models per domain."""

    def __init__(self, processed_dir: Path, models_dir: Path):
        self.processed_dir = Path(processed_dir)
        self.models_dir = Path(models_dir)
        self._cache: dict[str, dict[str, Any]] = {}

    # ── artifact loading ───────────────────────────────────────────────
    def _bundle(self, domain: str) -> dict[str, Any]:
        if domain in self._cache:
            return self._cache[domain]
        subdir = self.processed_dir / DOMAIN_DIRS[domain]
        if not subdir.exists():
            raise ModelNotAvailableError(
                f"Preprocessed artefacts for '{domain}' not found at {subdir}."
            )
        bundle: dict[str, Any] = {"dir": subdir}
        try:
            if domain == "crop":
                bundle["scaler"] = _load_joblib(subdir / "scaler.joblib")
                bundle["label_encoder"] = _load_joblib(subdir / "label_encoder.joblib")
                bundle["label_map"] = _load_json(subdir / "label_map.json")
            elif domain == "fertilizer":
                bundle["scaler"] = _load_joblib(subdir / "scaler.joblib")
                bundle["cat_encoder"] = _load_joblib(subdir / "categorical_encoder.joblib")
                bundle["target_encoder"] = _load_joblib(subdir / "target_encoder.joblib")
                bundle["fertilizer_map"] = _load_json(subdir / "fertilizer_map.json")
            elif domain == "yield":
                bundle["scaler"] = _load_joblib(subdir / "scaler.joblib")
                bundle["cat_encoder"] = _load_joblib(subdir / "categorical_encoder.joblib")
                bundle["feature_meta"] = _load_json(subdir / "feature_meta.json")
            elif domain == "irrigation":
                bundle["scaler"] = _load_joblib(subdir / "scaler.joblib")
                bundle["crop_encoder"] = _load_joblib(subdir / "crop_encoder.joblib")
                bundle["feature_meta"] = _load_json(subdir / "feature_meta.json")
                bundle["baseline"] = _load_json(subdir / "rule_based_baseline.json")
        except FileNotFoundError as exc:
            raise ModelNotAvailableError(
                f"Required preprocessing artefact missing for '{domain}': {exc.filename}"
            ) from exc

        # Load trained model if present (otherwise leave None).
        model_path = self.models_dir / DOMAIN_DIRS[domain] / "model.joblib"
        bundle["model"] = _load_joblib(model_path) if model_path.exists() else None
        bundle["model_path"] = str(model_path)
        self._cache[domain] = bundle
        logger.info("Loaded ML artefacts for '%s' (model=%s)", domain, bundle["model"] is not None)
        return bundle

    def _require_model(self, bundle: dict[str, Any], domain: str):
        model = bundle.get("model")
        if model is None:
            raise ModelNotAvailableError(
                f"No trained model for '{domain}'. Expected file: {bundle['model_path']}. "
                "Run: python -m ml.train_models"
            )
        return model

    # ── public predict API ─────────────────────────────────────────────
    def predict_crop(self, data: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        b = self._bundle("crop")
        model = self._require_model(b, "crop")
        row = np.array([[float(data[f]) for f in CROP_NUMERIC]], dtype=float)
        scaled = b["scaler"].transform(row)
        pred_idx = int(model.predict(scaled)[0])
        crop = b["label_encoder"].inverse_transform([pred_idx])[0]
        details = {}
        if hasattr(model, "predict_proba"):
            try:
                proba = model.predict_proba(scaled)[0]
                order = proba.argsort()[::-1][:3]
                classes = b["label_encoder"].inverse_transform(order)
                details["top"] = [
                    {"crop": str(c), "probability": round(float(p), 4)}
                    for c, p in zip(classes, proba[order])
                ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("predict_proba failed for crop: %s", exc)
        return {"prediction": str(crop), "details": details}

    def predict_fertilizer(self, data: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        b = self._bundle("fertilizer")
        model = self._require_model(b, "fertilizer")
        numeric = [float(data[k.lower()]) for k in FERT_NUMERIC]
        # The OrdinalEncoder was fit on title-cased strings — match that exactly.
        soil = str(data["soil_type"]).strip().title()
        crop = str(data["crop_type"]).strip().title()
        cat = b["cat_encoder"].transform([[soil, crop]])
        numeric_scaled = b["scaler"].transform([numeric])
        feature = np.concatenate([numeric_scaled[0], cat[0]]).reshape(1, -1)
        pred_idx = int(model.predict(feature)[0])
        fertilizer = b["target_encoder"].inverse_transform([pred_idx])[0]
        return {"prediction": str(fertilizer), "details": {"soil_type": soil, "crop_type": crop}}

    def predict_yield(self, data: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        b = self._bundle("yield")
        model = self._require_model(b, "yield")
        cats = [str(data["state_name"]).strip(), str(data["season"]).strip(), str(data["crop"]).strip()]
        numeric = [float(data["crop_year"]), float(data["area"]),
                   float(data["annual_rainfall"]), float(data["fertilizer"]), float(data["pesticide"])]
        cat_enc = b["cat_encoder"].transform([cats])
        numeric_scaled = b["scaler"].transform([numeric])
        feature = np.concatenate([cat_enc[0], numeric_scaled[0]]).reshape(1, -1)
        pred_log = float(model.predict(feature)[0])
        tonnes_per_ha = max(0.0, float(np.expm1(pred_log)))
        return {"prediction": round(tonnes_per_ha, 3), "details": {"unit": "tonnes_per_hectare"}}

    def predict_irrigation(self, data: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        b = self._bundle("irrigation")
        numeric = [float(data["soil_moisture"]), float(data.get("soil_temperature") or 0),
                   float(data.get("temperature") or 0), float(data.get("humidity") or 0),
                   float(data.get("crop_days") or 0)]
        model = b.get("model")
        if model is not None:
            classes = list(b["crop_encoder"].classes_)
            crop_val = _resolve_irrigation_crop(data.get("crop_type"), classes)
            crop_idx = int(b["crop_encoder"].transform([crop_val])[0])
            numeric_scaled = b["scaler"].transform([numeric])
            feature = np.concatenate([numeric_scaled[0], [crop_idx]]).reshape(1, -1)
            pred = int(model.predict(feature)[0])
            label = "Irrigate" if pred == 1 else "No irrigation"
            return {"prediction": pred, "label": label, "source": "model",
                    "details": {"crop_type": crop_val}}
        # Existing rule-based baseline (documented in rule_based_baseline.json) — not fabricated.
        baseline = b["baseline"]
        threshold = float(baseline.get("threshold_pct", 30.0))
        pred = 1 if float(data["soil_moisture"]) < threshold else 0
        label = "Irrigate" if pred == 1 else "No irrigation"
        return {"prediction": pred, "label": label, "source": "baseline",
                "details": {"rule": baseline.get("rule", f"soil_moisture < {threshold}"),
                            "threshold": threshold}}

    def status(self) -> dict[str, Any]:
        """Report which domains have models available (for /api/health/ml)."""
        out = {}
        for domain in DOMAIN_DIRS:
            try:
                b = self._bundle(domain)
                out[domain] = {"preprocessing": True, "model": b["model"] is not None,
                               "model_path": b["model_path"]}
            except ModelNotAvailableError as exc:
                out[domain] = {"preprocessing": False, "model": False, "error": exc.detail}
        return out


_adapter: MLAdapter | None = None


def get_adapter() -> MLAdapter:
    global _adapter
    if _adapter is None:
        s = get_settings()
        _adapter = MLAdapter(s.ml_processed_dir, s.ml_models_dir)
    return _adapter
