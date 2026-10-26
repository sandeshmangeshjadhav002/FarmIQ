"""Optional: train real models from the existing preprocessed datasets.

This is NOT run automatically. The trained model files do not exist in the
repo (only preprocessing artefacts do). Run this once to enable live
predictions for crop / fertilizer / yield / irrigation:

    cd backend
    .venv\\Scripts\\activate
    python -m ml.train_models

It reads the already-scaled/encoded train.csv files produced by
FarmIQ-rag/src/preprocess_*.py, fits a real (not dummy) sklearn estimator for
each domain, and saves model.joblib next to the encoders. The adapter in
ml/adapter.py will pick these up automatically on the next request.

Models are intentionally lightweight RandomForest estimators. Replace the
files under FarmIQ-rag/models/<domain>/ with your own if you have better ones.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from ml.adapter import DOMAIN_DIRS

logger = logging.getLogger("farmiq.ml.train")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# (domain, feature columns, target column, builder)
import pandas as pd  # noqa: E402
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor  # noqa: E402
import joblib  # noqa: E402

SPECS = {
    "crop": (
        ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"],
        "label_encoded",
        lambda: RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
    ),
    "fertilizer": (
        ["Temparature", "Humidity", "Moisture", "Nitrogen", "Potassium",
         "Phosphorous", "Soil Type", "Crop Type"],
        "fertilizer_encoded",
        lambda: RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
    ),
    "yield": (
        ["State_Name", "Season", "Crop", "Crop_Year", "Area",
         "Annual_Rainfall", "Fertilizer", "Pesticide"],
        "log_yield",
        lambda: RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1),
    ),
    "irrigation": (
        ["SoilMoisture", "SoilTemperature", "Temperature", "Humidity", "CropDays", "CropType"],
        "Irrigation",
        lambda: RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
    ),
}


def train_domain(domain: str, processed_dir: Path, models_dir: Path) -> None:
    feats, target, build = SPECS[domain]
    train_csv = processed_dir / DOMAIN_DIRS[domain] / "train.csv"
    if not train_csv.exists():
        logger.warning("[skip] %s: train.csv not found at %s", domain, train_csv)
        return
    df = pd.read_csv(train_csv)
    X = df[feats].values
    y = df[target].values
    model = build()
    model.fit(X, y)
    out_dir = models_dir / DOMAIN_DIRS[domain]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "model.joblib"
    joblib.dump(model, out_path)
    logger.info("[ok] %s: trained on %d rows -> %s", domain, len(df), out_path)


def main() -> None:
    s = get_settings()
    processed, models = s.ml_processed_dir, s.ml_models_dir
    logger.info("Processed dir: %s", processed)
    logger.info("Models dir:    %s", models)
    for domain in SPECS:
        try:
            train_domain(domain, processed, models)
        except Exception as exc:  # noqa: BLE001
            logger.error("[fail] %s: %s", domain, exc)
    logger.info("Done. Restart the backend (or reload) so the adapter picks up the new models.")


if __name__ == "__main__":
    main()
