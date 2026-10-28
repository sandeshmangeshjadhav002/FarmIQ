"""ML adapter tests: preprocessing artefacts load; 501 when no model;
irrigation baseline; a real model file is loaded and used when present."""
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from app.config import get_settings
from app.errors import ModelNotAvailableError
from ml import adapter as ml_adapter
from ml.adapter import MLAdapter

CROP_INPUT = {"N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80,
              "ph": 6.5, "rainfall": 200}

# The training artefacts, used to derive the expected feature order rather than
# restating it (a restated constant would pass even if both were reordered).
PROCESSED = Path(__file__).resolve().parents[2] / "FarmIQ-rag" / "datasets" / "processed"


def _adapter(ml_tmp_models):
    s = get_settings()
    return MLAdapter(s.ml_processed_dir, ml_tmp_models)


def test_irrigation_baseline_when_no_model(ml_tmp_models):
    a = _adapter(ml_tmp_models)
    out = a.predict_irrigation({"soil_moisture": 20.0, "temperature": 30,
                                "humidity": 60, "crop_days": 10, "crop_type": "Paddy"})
    assert out["source"] == "baseline"
    assert out["prediction"] == 1
    assert out["label"] == "Irrigate"


def test_crop_501_without_model(ml_tmp_models):
    a = _adapter(ml_tmp_models)
    with pytest.raises(ModelNotAvailableError):
        a.predict_crop(CROP_INPUT)


def test_fertilizer_501_without_model(ml_tmp_models):
    a = _adapter(ml_tmp_models)
    with pytest.raises(ModelNotAvailableError):
        a.predict_fertilizer({"temparature": 26, "humidity": 60, "moisture": 40,
                              "nitrogen": 80, "potassium": 20, "phosphorous": 30,
                              "soil_type": "Loamy", "crop_type": "Wheat"})


def test_yield_501_without_model(ml_tmp_models):
    a = _adapter(ml_tmp_models)
    with pytest.raises(ModelNotAvailableError):
        a.predict_yield({"state_name": "Maharashtra", "season": "Kharif", "crop": "Rice",
                         "crop_year": 2018, "area": 1.0, "annual_rainfall": 1000,
                         "fertilizer": 50, "pesticide": 5})


def test_crop_loads_real_model_file(ml_tmp_models):
    # Train a tiny real classifier (needs >=2 classes) and save it where the adapter looks.
    # Class 0 is the majority so a constant-zero input predicts class 0 -> "apple".
    model = LogisticRegression(max_iter=200)
    model.fit(np.zeros((4, 7)), np.array([0, 0, 0, 1]))
    d = ml_tmp_models / "crop_recommendation"
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib")

    a = MLAdapter(get_settings().ml_processed_dir, ml_tmp_models)
    out = a.predict_crop(CROP_INPUT)
    assert isinstance(out["prediction"], str)
    assert out["prediction"] == "apple"  # label_encoder class 0


def test_status_reports_all_domains(ml_tmp_models):
    a = _adapter(ml_tmp_models)
    status = a.status()
    for domain in ("crop", "fertilizer", "yield", "irrigation"):
        assert status[domain]["preprocessing"] is True
        assert status[domain]["model"] is False  # no trained models committed


# ── Feature-order verification ─────────────────────────────────────────────
# A model is only meaningful if inference feeds each feature into the exact
# position it occupied during training; otherwise the model silently scores
# nonsense. The expected order comes from the shipped artefacts (the column
# order of the preprocessed CSVs / ``feature_meta.json``), not from a copy of
# the constant, so reordering either side fails the test loudly.

def _csv_header(relative_path: str) -> list[str]:
    with open(PROCESSED / relative_path, "r", encoding="utf-8") as fh:
        return fh.readline().strip().split(",")


def _feature_meta(domain_dir: str) -> dict:
    return json.loads((PROCESSED / domain_dir / "feature_meta.json").read_text(encoding="utf-8"))


def test_crop_feature_order_matches_training_columns():
    header = _csv_header("crop_recommendation/train.csv")
    assert header[: len(ml_adapter.CROP_NUMERIC)] == ml_adapter.CROP_NUMERIC


def test_fertilizer_feature_order_matches_training_columns():
    header = _csv_header("fertilizer_recommendation/train.csv")
    n, c = len(ml_adapter.FERT_NUMERIC), len(ml_adapter.FERT_CATEGORICAL)
    assert header[:n] == ml_adapter.FERT_NUMERIC
    assert header[n:n + c] == ml_adapter.FERT_CATEGORICAL


def test_yield_feature_order_matches_feature_meta():
    meta = _feature_meta("crop_yield_india")
    assert meta["categorical_features"] == ml_adapter.YIELD_CATEGORICAL
    assert meta["numeric_features"] == ml_adapter.YIELD_NUMERIC
    # predict_yield concatenates categorical-block then numeric-block.
    assert meta["all_features"] == ml_adapter.YIELD_CATEGORICAL + ml_adapter.YIELD_NUMERIC


def test_irrigation_feature_order_matches_feature_meta():
    meta = _feature_meta("irrigation")
    assert meta["numeric_features"] == ml_adapter.IRR_NUMERIC
    # predict_irrigation concatenates the numeric block then the crop column.
    assert meta["all_features"] == ml_adapter.IRR_NUMERIC + meta["categorical_features"]
