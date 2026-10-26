"""Top-3 crop recommendation tests (feature 3).

These tests train a *real* scikit-learn model into a temporary models directory
and drive the actual ``ml.adapter`` code path, so the assertions are about the
model's own ``predict_proba`` output — no score is invented anywhere.

  * a probabilistic classifier must yield exactly three ranked recommendations
    whose scores are labelled ``probability`` and are non-increasing;
  * a model with fewer classes must yield fewer recommendations;
  * a classifier *without* ``predict_proba`` (``LinearSVC``) must report the
    limitation (``recommendations: null``) rather than fabricate scores.
"""
import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import LinearSVC

from app.config import get_settings
from ml.adapter import MLAdapter

CROP_INPUT = {"N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80,
              "ph": 6.5, "rainfall": 200}


def _adapter(models_dir):
    return MLAdapter(get_settings().ml_processed_dir, models_dir)


def _train_crop_model(models_dir, estimator, n_classes=5, n_rows=60):
    """Fit ``estimator`` and save it where the adapter looks for crop models.

    Predictions are meaningless (the features are random) — what matters is
    that the adapter reads genuine ``predict_proba`` output from a real fitted
    scikit-learn estimator paired with the repository's fitted label encoder.
    """
    rng = np.random.RandomState(0)
    x = rng.rand(n_rows, 7)
    y = np.arange(n_rows) % n_classes
    estimator.fit(x, y)
    target = models_dir / "crop_recommendation"
    target.mkdir(parents=True, exist_ok=True)
    joblib.dump(estimator, target / "model.joblib")
    return estimator


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def test_top_three_from_the_models_own_probabilities(ml_tmp_models):
    _train_crop_model(ml_tmp_models, RandomForestClassifier(n_estimators=8, random_state=0))

    out = _adapter(ml_tmp_models).predict_crop(CROP_INPUT)
    recs = out["recommendations"]

    assert recs is not None and len(recs) == 3
    assert [r["rank"] for r in recs] == [1, 2, 3]
    assert out["score_type"] == "probability"
    assert all(r["score_type"] == "probability" for r in recs)
    assert all(r["score_label"] for r in recs)

    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True), "recommendations must be ranked"
    assert all(0.0 <= s <= 1.0 for s in scores), "a probability must be within [0, 1]"

    # Crop names come from the repository's real fitted label encoder.
    assert all(isinstance(r["crop"], str) and r["crop"] for r in recs)
    assert len({r["crop"] for r in recs}) == 3
    # The top recommendation is the model's own argmax prediction.
    assert out["prediction"] == recs[0]["crop"]
    # The legacy ``details.top`` shape is still emitted for the older frontend.
    assert out["details"]["top"][0] == {"crop": recs[0]["crop"], "probability": recs[0]["score"]}


def test_fewer_recommendations_than_three_when_the_model_has_two_classes(ml_tmp_models):
    _train_crop_model(ml_tmp_models, RandomForestClassifier(n_estimators=8, random_state=0),
                      n_classes=2)

    recs = _adapter(ml_tmp_models).predict_crop(CROP_INPUT)["recommendations"]
    assert recs is not None and len(recs) == 2
    assert [r["rank"] for r in recs] == [1, 2]


def test_model_without_probability_support_reports_the_limitation(ml_tmp_models):
    """LinearSVC has no ``predict_proba``: report that instead of inventing a score."""
    assert not hasattr(LinearSVC(), "predict_proba")
    _train_crop_model(ml_tmp_models, LinearSVC(random_state=0), n_classes=4)

    out = _adapter(ml_tmp_models).predict_crop(CROP_INPUT)
    assert out["recommendations"] is None
    assert out["score_type"] is None
    assert "top" not in out["details"]
    # The hard prediction is still returned — only the ranking is unavailable.
    assert isinstance(out["prediction"], str) and out["prediction"]


def test_crop_endpoint_returns_three_ranked_cards(app_client, fake_client, ml_tmp_models):
    _train_crop_model(ml_tmp_models, RandomForestClassifier(n_estimators=8, random_state=0))
    h = _auth(fake_client)

    r = app_client.post("/api/predictions/crop", json=CROP_INPUT, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["domain"] == "crop"
    assert body["score_type"] == "probability"
    assert len(body["recommendations"]) == 3
    assert body["prediction"] == body["recommendations"][0]["crop"]
    assert body["advisory"], "the 'confidence != field success' advisory must be present"
    assert body["source"] == "model"


def test_crop_endpoint_warns_on_valid_but_out_of_training_range_value(app_client, fake_client, ml_tmp_models):
    """N = 180 is inside the supported range (<=200) but above the crop
    dataset's maximum (140): the prediction runs and a warning is returned."""
    _train_crop_model(ml_tmp_models, RandomForestClassifier(n_estimators=8, random_state=0))
    h = _auth(fake_client)

    r = app_client.post("/api/predictions/crop", json={**CROP_INPUT, "N": 180}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert any(u["field"] == "N" for u in body["unusual"])
    assert any("training" in w.lower() for w in body["warnings"])
    assert body["recommendations"], "the prediction still runs for a valid-but-unusual value"


@pytest.mark.parametrize("domain", ["crop", "fertilizer", "yield", "irrigation"])
def test_schema_advisory_is_served_for_every_domain(app_client, domain):
    r = app_client.get(f"/api/predictions/schema/{domain}")
    assert r.status_code == 200, r.text
    assert "does not guarantee" in r.json()["advisory"]
