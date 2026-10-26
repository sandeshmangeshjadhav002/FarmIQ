"""Model evaluation on the repository's own held-out test split.

Run from ``backend/``::

    python -m ml.evaluate

What it does
------------
For every domain it loads the **existing** trained model and the **existing**
held-out ``test.csv`` produced by ``FarmIQ-rag/src/preprocess_*.py``, runs the
model over that split, and computes real metrics with scikit-learn. Nothing is
re-split, so there is no train/test leakage introduced here, and no metric is
hardcoded — if a model or dataset is missing the domain is reported as
``available: false`` with the reason instead of a fabricated number.

Reported metrics
----------------
* Classification (crop, fertilizer, irrigation): accuracy, macro & weighted
  precision/recall/F1, a confusion matrix, a per-class breakdown, and (for crop,
  whose model exposes ``predict_proba``) top-3 accuracy.
* Regression (yield): RMSE / MAE / R² on the log target the model was trained on,
  plus RMSE / MAE on the original tonnes-per-hectare scale.

Writes ``ml/reports/evaluation_report.json`` and ``.md`` next to this file.
"""
from __future__ import annotations

import json
import logging
import platform
import sys
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger("farmiq.ml.evaluate")

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

# Methodologies, taken from the preprocessing scripts themselves.
_SPLITS: dict[str, dict[str, Any]] = {
    "crop": {
        "kind": "stratified hold-out",
        "detail": "train_test_split(test_size=0.20, random_state=42, stratify=y) "
                  "in preprocess_crop_recommendation.py",
    },
    "fertilizer": {
        "kind": "stratified hold-out",
        "detail": "train_test_split(test_size=0.20, random_state=42, stratify=y) "
                  "in preprocess_fertilizer_recommendation.py",
    },
    "irrigation": {
        "kind": "stratified hold-out",
        "detail": "train_test_split(test_size=0.20, random_state=42, stratify=y) "
                  "in preprocess_irrigation.py",
    },
    "yield": {
        "kind": "temporal hold-out",
        "detail": "Crop_Year <= 2013 -> train, Crop_Year > 2013 -> test "
                  "(preprocess_crop_yield.py, TRAIN_YEARS_MAX = 2013)",
    },
}

# Feature column names in the processed CSVs (already scaled/encoded on disk).
_FEATURE_COLUMNS: dict[str, list[str]] = {
    "crop": ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"],
    "fertilizer": ["Temparature", "Humidity", "Moisture", "Nitrogen", "Potassium",
                   "Phosphorous", "Soil Type", "Crop Type"],
    "yield": ["State_Name", "Season", "Crop", "Crop_Year", "Area",
              "Annual_Rainfall", "Fertilizer", "Pesticide"],
    "irrigation": ["SoilMoisture", "SoilTemperature", "Temperature", "Humidity",
                   "CropDays", "CropType"],
}

_TARGET_COLUMN: dict[str, str] = {
    "crop": "label_encoded",
    "fertilizer": "fertilizer_encoded",
    "yield": "log_yield",
    "irrigation": "Irrigation",
}

_MODEL_SUBDIR: dict[str, str] = {
    "crop": "crop_recommendation",
    "fertilizer": "fertilizer_recommendation",
    "yield": "crop_yield_india",
    "irrigation": "irrigation",
}

_CAVEATS = [
    "These metrics come from the repository's public datasets snapshots "
    "(Kaggle-sourced), not from FarmIQ field trials.",
    "The datasets are limited in size and geographic coverage and may not "
    "represent real field conditions in any particular location.",
    "The fertilizer and irrigation test splits are very small (tens of rows), "
    "so their metrics are indicative only and carry wide uncertainty.",
    "A model's test-set score is not a guarantee of accuracy on a real farm: "
    "it measures agreement with this dataset, nothing more.",
    "The yield model is evaluable as a regression but has no notion of "
    "'probability', so no confidence figures are reported for it.",
]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def _load_label_map(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            out[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def _load_model(path: Path) -> tuple[Any, list[str]]:
    """Load a joblib model, capturing any unpickle-version warnings."""
    import joblib

    if not path.exists():
        return None, []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = joblib.load(path)
    messages = [f"{type(w.message).__name__}: {w.message}" for w in caught]
    return model, messages


def _classification_report_block(y_true: list, y_pred: list, labels: list, names: dict[int, str]) -> dict[str, Any]:
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    p_w, r_w, f_w, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0
    )
    p_m, r_m, f_m, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=labels).tolist()
    per_class = [
        {
            "label": names.get(int(label), str(label)),
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
            "support": int(support[i]),
        }
        for i, label in enumerate(labels)
    ]
    return {
        "precision_macro": round(float(p_m), 4),
        "recall_macro": round(float(r_m), 4),
        "f1_macro": round(float(f_m), 4),
        "precision_weighted": round(float(p_w), 4),
        "recall_weighted": round(float(r_w), 4),
        "f1_weighted": round(float(f_w), 4),
        "confusion_matrix": matrix,
        "confusion_matrix_labels": [names.get(int(l), str(l)) for l in labels],
        "per_class": per_class,
    }


def _eval_classifier(domain: str, processed: Path, models: Path) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import accuracy_score

    subdir = _MODEL_SUBDIR[domain]
    test_path = processed / subdir / "test.csv"
    train_path = processed / subdir / "train.csv"
    model_path = models / subdir / "model.joblib"

    if not test_path.exists():
        return {"available": False, "reason": f"test split not found at {test_path}"}
    model, load_warnings = _load_model(model_path)
    if model is None:
        return {"available": False, "reason": f"model file not found at {model_path}"}

    rows = _read_csv_rows(test_path)
    n_train = len(_read_csv_rows(train_path)) if train_path.exists() else None
    features = _FEATURE_COLUMNS[domain]

    X = np.array([[float(r[c]) for c in features] for r in rows], dtype=float)
    y_true_all = [int(float(r[_TARGET_COLUMN[domain]])) for r in rows]

    model_classes = [int(c) for c in getattr(model, "classes_", sorted(set(y_true_all)))]
    known = set(model_classes)
    keep = [i for i, y in enumerate(y_true_all) if y in known]
    X, y_true = X[keep], [y_true_all[i] for i in keep]

    y_pred = [int(v) for v in model.predict(X)]

    names = _label_names(domain, processed, subdir, model_classes)

    block: dict[str, Any] = {
        "available": True,
        "task": "multiclass_classification",
        "model_type": type(model).__name__,
        "model_path": str(model_path),
        "test_file": str(test_path),
        "n_train": n_train,
        "n_test": len(rows),
        "n_test_scored": len(y_true),
        "n_test_excluded": len(rows) - len(y_true),
        "n_classes": len(model_classes),
        "classes": [names.get(c, str(c)) for c in model_classes],
        "split": _SPLITS[domain],
        "metrics": {
            "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
            **_classification_report_block(y_true, y_pred, model_classes, names),
        },
    }

    # Top-3 accuracy — only where the model exposes real probabilities.
    if hasattr(model, "predict_proba"):
        from sklearn.metrics import top_k_accuracy_score
        proba = model.predict_proba(X)
        k = min(3, len(model_classes))
        try:
            block["metrics"]["top_k"] = k
            block["metrics"][f"top_{k}_accuracy"] = round(
                float(top_k_accuracy_score(y_true, proba, k=k, labels=model_classes)), 4
            )
        except ValueError as exc:  # e.g. a class missing from the test split
            block["metrics"]["top_k_note"] = (
                f"top-{k} accuracy unavailable on this split: {exc}"
            )
    else:
        block["metrics"]["top_k_note"] = (
            "model does not expose predict_proba; no probability-based metric reported"
        )

    if load_warnings:
        block["load_warnings"] = load_warnings
    return block


def _label_names(domain: str, processed: Path, subdir: str, classes: list[int]) -> dict[int, str]:
    if domain == "crop":
        return _load_label_map(processed / subdir / "label_map.json")
    if domain == "fertilizer":
        return _load_label_map(processed / subdir / "fertilizer_map.json")
    if domain == "irrigation":
        meta_path = processed / subdir / "feature_meta.json"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            raw = meta.get("target_encoding") or {}
            return {int(k): str(v) for k, v in raw.items()}
    return {c: str(c) for c in classes}


def _eval_regression(domain: str, processed: Path, models: Path) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    subdir = _MODEL_SUBDIR[domain]
    test_path = processed / subdir / "test.csv"
    train_path = processed / subdir / "train.csv"
    model_path = models / subdir / "model.joblib"

    if not test_path.exists():
        return {"available": False, "reason": f"test split not found at {test_path}"}
    model, load_warnings = _load_model(model_path)
    if model is None:
        return {"available": False, "reason": f"model file not found at {model_path}"}

    rows = _read_csv_rows(test_path)
    n_train = len(_read_csv_rows(train_path)) if train_path.exists() else None
    features = _FEATURE_COLUMNS[domain]

    X = np.array([[float(r[c]) for c in features] for r in rows], dtype=float)
    y_log = np.array([float(r["log_yield"]) for r in rows], dtype=float)
    y_actual = np.array([float(r["Yield_tonnes_per_ha"]) for r in rows], dtype=float)

    pred_log = np.asarray(model.predict(X), dtype=float)
    pred_actual = np.clip(np.expm1(pred_log), 0.0, None)

    block: dict[str, Any] = {
        "available": True,
        "task": "regression",
        "model_type": type(model).__name__,
        "model_path": str(model_path),
        "test_file": str(test_path),
        "n_train": n_train,
        "n_test": len(rows),
        "split": _SPLITS[domain],
        "target": "log_yield (log of Yield_tonnes_per_ha)",
        "metrics": {
            "rmse_log": round(float(np.sqrt(mean_squared_error(y_log, pred_log))), 4),
            "mae_log": round(float(mean_absolute_error(y_log, pred_log)), 4),
            "r2_log": round(float(r2_score(y_log, pred_log)), 4),
            "rmse_tonnes_per_ha": round(
                float(np.sqrt(mean_squared_error(y_actual, pred_actual))), 4),
            "mae_tonnes_per_ha": round(
                float(mean_absolute_error(y_actual, pred_actual)), 4),
            "r2_tonnes_per_ha": round(float(r2_score(y_actual, pred_actual)), 4),
            "note": (
                "The model predicts log_yield; the tonnes/ha metrics apply expm1 to "
                "the prediction and compare against the dataset's yield column."
            ),
        },
    }
    if load_warnings:
        block["load_warnings"] = load_warnings
    return block


def _environment() -> dict[str, Any]:
    import numpy
    import pandas
    import sklearn

    return {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "platform": platform.platform(),
    }


def run(write: bool = True, reports_dir: Optional[Path] = None) -> dict[str, Any]:
    """Evaluate every domain and (optionally) write the JSON + Markdown report."""
    settings = get_settings()
    processed = settings.ml_processed_dir
    models = settings.ml_models_dir
    target_dir = reports_dir or REPORTS_DIR

    domains: dict[str, Any] = {}
    for domain in ("crop", "fertilizer", "yield", "irrigation"):
        try:
            if domain == "yield":
                domains[domain] = _eval_regression(domain, processed, models)
            else:
                domains[domain] = _eval_classifier(domain, processed, models)
        except Exception as exc:  # noqa: BLE001 - report, never crash the script
            logger.exception("Evaluation failed for %s", domain)
            domains[domain] = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    report = {
        "report_title": "FarmIQ ML Evaluation Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_date": date.today().isoformat(),
        "dataset_root": str(processed),
        "models_root": str(models),
        "environment": _environment(),
        "methodology": {
            "summary": (
                "Each domain is scored on the held-out split that ships in "
                "datasets/processed/<domain>/test.csv. That split was created by "
                "the repository's own preprocessing scripts; this evaluation does "
                "not re-split the data, so no train/test leakage is introduced."
            ),
            "splits": _SPLITS,
            "metrics": {
                "classification": [
                    "accuracy", "precision (macro/weighted)", "recall (macro/weighted)",
                    "F1 (macro/weighted)", "confusion matrix", "per-class breakdown",
                ],
                "regression": ["RMSE", "MAE", "R² (log target and tonnes/ha)"],
            },
        },
        "caveats": _CAVEATS,
        "domains": domains,
    }

    if write:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "evaluation_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        (target_dir / "evaluation_report.md").write_text(_to_markdown(report), encoding="utf-8")
        logger.info("Wrote evaluation report to %s", target_dir)
    return report


def _to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# {report['report_title']}",
        "",
        f"- **Evaluation date:** {report['evaluation_date']}",
        f"- **Generated at:** {report['generated_at']}",
        f"- **Datasets:** `{report['dataset_root']}`",
        f"- **Models:** `{report['models_root']}`",
        "",
        "## Methodology",
        "",
        report["methodology"]["summary"],
        "",
    ]
    for domain, split in report["methodology"]["splits"].items():
        lines.append(f"- **{domain}** — {split['kind']}: {split['detail']}")
    lines += ["", "## Results", ""]

    for domain, block in report["domains"].items():
        lines.append(f"### {domain}")
        lines.append("")
        if not block.get("available"):
            lines.append(f"_Not evaluated:_ {block.get('reason')}")
            lines.append("")
            continue
        lines.append(f"- Model: `{block['model_type']}` (`{block['task']}`)")
        lines.append(f"- Train samples: {block.get('n_train')} · Test samples: {block.get('n_test')}")
        if block["task"] == "multiclass_classification":
            lines.append(f"- Classes: {block['n_classes']}")
        lines.append("")
        for key, value in block["metrics"].items():
            if key in {"confusion_matrix", "confusion_matrix_labels", "per_class"}:
                continue
            lines.append(f"- **{key}**: {value}")
        lines.append("")
        if "confusion_matrix" in block["metrics"]:
            labels = block["metrics"]["confusion_matrix_labels"]
            lines.append("**Confusion matrix** (rows = actual, cols = predicted)")
            lines.append("")
            lines.append("| | " + " | ".join(labels) + " |")
            lines.append("|" + "---|" * (len(labels) + 1))
            for label, row in zip(labels, block["metrics"]["confusion_matrix"]):
                lines.append(f"| {label} | " + " | ".join(str(v) for v in row) + " |")
            lines.append("")
        if "load_warnings" in block:
            lines.append("**Load warnings**")
            for w in block["load_warnings"]:
                lines.append(f"- {w}")
            lines.append("")

    lines += ["## Caveats", ""]
    lines += [f"- {c}" for c in report["caveats"]]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    report = run()
    available = [d for d, b in report["domains"].items() if b.get("available")]
    print(f"Evaluation complete. Evaluated: {', '.join(available) or 'none'}")
    for domain, block in report["domains"].items():
        if block.get("available") and block["task"] == "multiclass_classification":
            m = block["metrics"]
            print(f"  {domain:11s} accuracy={m['accuracy']:.4f}  f1_macro={m['f1_macro']:.4f}  "
                  f"n_test={block['n_test']}")
        elif block.get("available"):
            m = block["metrics"]
            print(f"  {domain:11s} r2={m['r2_log']:.4f}  rmse(log)={m['rmse_log']:.4f}  "
                  f"n_test={block['n_test']}")
        else:
            print(f"  {domain:11s} not evaluated: {block.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
