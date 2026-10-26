"""
FarmIQ-ML — Crop Recommendation Preprocessing
================================================
Dataset : Kaggle — atharvaingle/crop-recommendation-dataset
Task    : Multi-class classification (22 crops)
Columns : N, P, K, temperature, humidity, ph, rainfall → label

Pipeline:
  1. Load raw CSV
  2. Validate expected columns
  3. Remove duplicates
  4. Handle missing values (none expected, but guarded)
  5. Validate numeric ranges
  6. Encode target label (LabelEncoder, mapping saved)
  7. Scale numeric features (StandardScaler)
  8. Stratified train/test split (80/20)
  9. Save processed artefacts to datasets/processed/crop_recommendation/

No data leakage: scaler is fit on training data only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
import joblib

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠→)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "datasets" / "raw" / "crop_recommendation" / "Crop_recommendation.csv"
OUT_DIR = PROJECT_ROOT / "datasets" / "processed" / "crop_recommendation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FEATURE_COLS = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
TARGET_COL = "label"
RANDOM_STATE = 42
TEST_SIZE = 0.20

VALID_RANGES: dict[str, tuple[float, float]] = {
    "N": (0, 200),
    "P": (0, 200),
    "K": (0, 250),
    "temperature": (0.0, 55.0),
    "humidity": (0.0, 100.0),
    "ph": (0.0, 14.0),
    "rainfall": (0.0, 3000.0),
}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(raw_path: Path = RAW_PATH, out_dir: Path = OUT_DIR) -> dict:
    """
    Execute the full preprocessing pipeline.
    Returns a summary dict with artefact paths and statistics.
    Raises FileNotFoundError if raw CSV is absent.
    """
    # ── 1. Load ──────────────────────────────────────────────────────
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Raw CSV not found: {raw_path}\n"
            "Run: python src/download_datasets.py"
        )
    df = pd.read_csv(raw_path)
    print(f"[crop_recommendation] Loaded  : {len(df):,} rows × {len(df.columns)} cols")

    # ── 2. Validate columns ───────────────────────────────────────────
    required = FEATURE_COLS + [TARGET_COL]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing expected columns: {missing_cols}\n"
                         f"Found: {list(df.columns)}")

    # ── 3. Drop duplicates ────────────────────────────────────────────
    n_before = len(df)
    df = df.drop_duplicates()
    n_dupes = n_before - len(df)
    if n_dupes:
        print(f"[crop_recommendation] Dropped  : {n_dupes:,} duplicate rows")

    # ── 4. Handle missing values ──────────────────────────────────────
    missing = df[FEATURE_COLS].isnull().sum()
    if missing.any():
        print(f"[crop_recommendation] Missing values detected — filling with column median:")
        for col in FEATURE_COLS:
            cnt = df[col].isnull().sum()
            if cnt:
                median_val = df[col].median()
                df[col] = df[col].fillna(median_val)
                print(f"  {col}: {cnt} nulls → median ({median_val:.4f})")
    missing_target = df[TARGET_COL].isnull().sum()
    if missing_target:
        df = df[df[TARGET_COL].notna()]
        print(f"[crop_recommendation] Dropped {missing_target} rows with null target")

    # ── 5. Range validation ───────────────────────────────────────────
    invalid_rows: list[int] = []
    for col, (lo, hi) in VALID_RANGES.items():
        mask = (df[col] < lo) | (df[col] > hi)
        n_bad = mask.sum()
        if n_bad:
            print(f"[crop_recommendation] ⚠ {col}: {n_bad} values outside [{lo},{hi}] — clipping")
            df[col] = df[col].clip(lo, hi)

    # ── 6. Encode target ──────────────────────────────────────────────
    le = LabelEncoder()
    df["label_encoded"] = le.fit_transform(df[TARGET_COL])
    label_map = {int(i): str(c) for i, c in enumerate(le.classes_)}
    print(f"[crop_recommendation] Classes  : {len(le.classes_)} → {list(le.classes_)[:5]} …")

    # ── 7. Split (stratified) ─────────────────────────────────────────
    X = df[FEATURE_COLS].values
    y = df["label_encoded"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"[crop_recommendation] Train    : {len(X_train):,}  |  Test: {len(X_test):,}")

    # ── 8. Scale features (fit on train only) ─────────────────────────
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # ── 9. Save artefacts ─────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    # Processed DataFrames
    train_df = pd.DataFrame(X_train_scaled, columns=FEATURE_COLS)
    train_df["label_encoded"] = y_train
    test_df = pd.DataFrame(X_test_scaled, columns=FEATURE_COLS)
    test_df["label_encoded"] = y_test

    train_path = out_dir / "train.csv"
    test_path = out_dir / "test.csv"
    train_df.to_csv(train_path, index=False)
    test_df.to_csv(test_path, index=False)

    # Scaler and encoder
    scaler_path = out_dir / "scaler.joblib"
    encoder_path = out_dir / "label_encoder.joblib"
    label_map_path = out_dir / "label_map.json"

    joblib.dump(scaler, scaler_path)
    joblib.dump(le, encoder_path)
    with open(label_map_path, "w") as f:
        json.dump(label_map, f, indent=2)

    _rel_out = str(out_dir.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in out_dir.parents or out_dir == PROJECT_ROOT else str(out_dir)
    print(f"[crop_recommendation] Saved to : {_rel_out}/")

    summary = {
        "dataset": "crop_recommendation",
        "raw_rows": n_before,
        "clean_rows": len(df),
        "duplicates_removed": n_dupes,
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "n_classes": len(le.classes_),
        "features": FEATURE_COLS,
        "target": TARGET_COL,
        "scaler": str(scaler_path),
        "encoder": str(encoder_path),
        "label_map": label_map_path,
        "train_csv": str(train_path),
        "test_csv": str(test_path),
    }
    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        summary = run()
        print("\nSummary:")
        for k, v in summary.items():
            print(f"  {k:<20}: {v}")
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
