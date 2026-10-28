"""MLOps: model evaluation report endpoint.

Serves the report produced by ``ml.evaluate`` — real metrics computed on the
repository's held-out test splits, never fabricated. The report is read from
``ml/reports/evaluation_report.json``; ``?refresh=true`` recomputes it from the
models and datasets on disk.

Nothing is recomputed on a normal request (the report is generated offline by
``python -m ml.evaluate``), so the endpoint is cheap and cannot fail a hackathon
demo because a model happens to be loading slowly.

Endpoints
---------
``GET /api/mlops/evaluation``          – summary + per-domain real metrics.
``GET /api/mlops/evaluation/summary``  – compact metrics only (for a dashboard card).

Authentication is required: this is an internal model-health view.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.errors import AppError

logger = logging.getLogger("farmiq.mlops")
router = APIRouter()

_REPORT_JSON = Path(__file__).resolve().parent.parent.parent / "ml" / "reports" / "evaluation_report.json"

# ``?refresh=true`` runs a full evaluation of every domain, which loads the
# models and the held-out splits. That is far too expensive to let concurrent
# requests duplicate, so only one recompute may be in flight per process.
_REFRESH_LOCK = threading.Lock()


def _read_report() -> dict[str, Any] | None:
    """Return the stored report, or ``None`` when it has not been generated."""
    if not _REPORT_JSON.exists():
        return None
    try:
        with open(_REPORT_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise AppError(
            500,
            f"The stored evaluation report is not valid JSON ({exc}). Run "
            "`python -m ml.evaluate` to regenerate it.",
        )


def _recompute() -> dict[str, Any]:
    try:
        from ml import evaluate
        return evaluate.run(write=True)
    except Exception as exc:  # noqa: BLE001 - surface a clear, honest error
        logger.exception("Evaluation run failed")
        raise AppError(
            503,
            "Model evaluation is unavailable: the models or datasets could "
            f"not be evaluated ({type(exc).__name__}). Run `python -m ml.evaluate` "
            "from the backend/ directory to see the full error.",
        )


def _load_report(refresh: bool) -> dict[str, Any]:
    if not refresh:
        report = _read_report()
        if report is not None:
            return report
        # No stored report yet: generate one, once, under the lock.

    if refresh and _REFRESH_LOCK.acquire(blocking=False):
        try:
            return _recompute()
        finally:
            _REFRESH_LOCK.release()

    if refresh:
        # Another request is already recomputing. Never stack a second full
        # evaluation — serve the stored report, or wait for the one in flight.
        report = _read_report()
        if report is not None:
            return report

    with _REFRESH_LOCK:
        report = _read_report()
        if report is not None:
            return report
        return _recompute()


@router.get("/api/mlops/evaluation")
def evaluation_report(
    refresh: bool = Query(False, description="Recompute the report from disk now."),
    user=Depends(get_current_user),
):
    """Full evaluation report: methodology, caveats and per-domain metrics."""
    report = _load_report(refresh)
    return {
        "report_title": report.get("report_title"),
        "generated_at": report.get("generated_at"),
        "evaluation_date": report.get("evaluation_date"),
        "environment": report.get("environment"),
        "methodology": report.get("methodology"),
        "caveats": report.get("caveats", []),
        "domains": report.get("domains", {}),
    }


@router.get("/api/mlops/evaluation/summary")
def evaluation_summary(
    refresh: bool = Query(False),
    user=Depends(get_current_user),
):
    """Compact per-domain headline metrics, for a dashboard card."""
    report = _load_report(refresh)
    summary: list[dict[str, Any]] = []
    for domain, block in report.get("domains", {}).items():
        if not block.get("available"):
            summary.append({
                "domain": domain,
                "available": False,
                "reason": block.get("reason"),
            })
            continue
        metrics = block.get("metrics", {})
        row: dict[str, Any] = {
            "domain": domain,
            "available": True,
            "task": block.get("task"),
            "model_type": block.get("model_type"),
            "n_train": block.get("n_train"),
            "n_test": block.get("n_test"),
            "n_classes": block.get("n_classes"),
        }
        if block.get("task") == "multiclass_classification":
            row.update({
                "accuracy": metrics.get("accuracy"),
                "f1_macro": metrics.get("f1_macro"),
                "top_3_accuracy": metrics.get("top_3_accuracy"),
            })
        else:
            row.update({
                "r2_log": metrics.get("r2_log"),
                "rmse_log": metrics.get("rmse_log"),
            })
        summary.append(row)

    return {
        "evaluation_date": report.get("evaluation_date"),
        "generated_at": report.get("generated_at"),
        "caveats": report.get("caveats", []),
        "domains": summary,
    }
