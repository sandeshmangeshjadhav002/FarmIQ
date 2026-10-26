"""MLOps evaluation-report tests (feature 5).

The report is produced offline by ``python -m ml.evaluate`` from the
repository's real held-out test splits. These tests assert the endpoint serves
that stored report — real metrics, honest caveats, no fabricated numbers — and
that it never recomputes anything (and therefore cannot fail mid-demo) on a
plain request.

If the report file is absent the metric assertions are skipped with a clear
reason rather than silently passing.
"""
from pathlib import Path

import pytest

REPORT_JSON = Path(__file__).resolve().parent.parent / "ml" / "reports" / "evaluation_report.json"
needs_report = pytest.mark.skipif(
    not REPORT_JSON.exists(),
    reason="run `python -m ml.evaluate` from backend/ to generate the report",
)


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def test_evaluation_requires_authentication(app_client):
    assert app_client.get("/api/mlops/evaluation").status_code == 401
    assert app_client.get("/api/mlops/evaluation/summary").status_code == 401


@needs_report
def test_evaluation_report_discloses_methodology_and_caveats(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.get("/api/mlops/evaluation", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["report_title"]
    assert body["evaluation_date"]
    assert body["generated_at"]
    assert body["methodology"]["splits"], "the train/test split must be disclosed"
    assert body["methodology"]["metrics"]
    assert len(body["caveats"]) >= 2, "dataset limitations must be disclosed"
    assert any("limited" in c.lower() or "not represent" in c.lower() for c in body["caveats"])


@needs_report
def test_crop_metrics_are_real_and_complete(app_client, fake_client):
    h = _auth(fake_client)
    body = app_client.get("/api/mlops/evaluation", headers=h).json()
    crop = body["domains"]["crop"]

    assert crop["available"] is True
    assert crop["task"] == "multiclass_classification"
    assert crop["n_train"] > 0 and crop["n_test"] > 0
    assert crop["n_classes"] == 22
    assert len(crop["classes"]) == 22
    assert crop["split"], "the test methodology must be recorded"

    metrics = crop["metrics"]
    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro"):
        assert 0.0 <= metrics[key] <= 1.0, key

    matrix = metrics["confusion_matrix"]
    assert len(matrix) == crop["n_classes"]
    assert all(len(row) == crop["n_classes"] for row in matrix)
    assert sum(sum(row) for row in matrix) == crop["n_test_scored"]
    assert len(metrics["confusion_matrix_labels"]) == crop["n_classes"]


@needs_report
def test_every_available_domain_reports_samples_and_metrics(app_client, fake_client):
    h = _auth(fake_client)
    body = app_client.get("/api/mlops/evaluation", headers=h).json()

    assert body["domains"], "the report must contain at least one domain"
    for name, block in body["domains"].items():
        assert "available" in block, name
        if not block["available"]:
            assert block.get("reason"), f"{name} must explain why it is not evaluated"
            continue
        assert block["n_train"] > 0, name
        assert block["n_test"] > 0, name
        assert block["metrics"], name
        assert block["model_path"], name


@needs_report
def test_summary_endpoint_is_compact(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.get("/api/mlops/evaluation/summary", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["evaluation_date"]
    assert body["caveats"]
    assert body["domains"]
    crop = next(d for d in body["domains"] if d["domain"] == "crop")
    assert crop["available"] is True
    assert crop["n_classes"] == 22
    assert 0.0 <= crop["accuracy"] <= 1.0
    assert "confusion_matrix" not in crop, "the summary must stay compact"


@needs_report
def test_report_is_served_from_disk_without_recomputing(app_client, fake_client, monkeypatch):
    """A plain request must not retrain models — the report is precomputed."""
    from ml import evaluate

    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("the endpoint must not recompute the report")

    monkeypatch.setattr(evaluate, "run", _boom)

    h = _auth(fake_client)
    assert app_client.get("/api/mlops/evaluation", headers=h).status_code == 200
    assert app_client.get("/api/mlops/evaluation/summary", headers=h).status_code == 200
