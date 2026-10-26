"""ML adapter tests: preprocessing artefacts load; 501 when no model;
irrigation baseline; a real model file is loaded and used when present."""
import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from app.config import get_settings
from app.errors import ModelNotAvailableError
from ml.adapter import MLAdapter

CROP_INPUT = {"N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80,
              "ph": 6.5, "rainfall": 200}


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
