"""
FarmIQ-ML — Crop Yield Prediction Preprocessing
=================================================
Dataset : Kaggle — abhinand05/crop-production-in-india
          (sourced from Government of India / ICRISAT records)
Task    : Regression — predict yield in tonnes per hectare
Columns : State_Name, District_Name, Crop_Year, Season, Crop,
          Area (hectares), Production (metric tonnes)
Target  : Yield_tonnes_per_ha = Production / Area  (derived)

Key decisions:
  - Production column is EXCLUDED from features (it directly encodes target).
  - Temporal split is used: years 1997–2013 → train, 2014+ → test.
    This evaluates out-of-sample generalisation better than random split.
  - Log-transform applied to target (right-skewed distribution).
  - Categorical features encoded with OrdinalEncoder.
  - Numeric features scaled with StandardScaler (fit on train only).

Pipeline:
  1. Load raw CSV, normalise column names
  2. Derive Yield_tonnes_per_ha
  3. Drop rows with zero area, null Production, extreme yield outliers
  4. Temporal train/test split
  5. Encode categoricals (fit on train)
  6. Scale numerics (fit on train)
  7. Log-transform target
  8. Save artefacts
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import OrdinalEncoder, StandardScaler
import joblib

warnings.filterwarnings("ignore", category=FutureWarning)

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠→)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "datasets" / "raw" / "crop_yield_india" / "crop_production.csv"
OUT_DIR = PROJECT_ROOT / "datasets" / "processed" / "crop_yield_india"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Canonical column name map: lowercase stripped → canonical
COL_MAP = {
    "state_name": "State_Name",
    "state": "State_Name",
    "district_name": "District_Name",
    "district": "District_Name",
    "crop_year": "Crop_Year",
    "year": "Crop_Year",
    "season": "Season",
    "crop": "Crop",
    "area": "Area",
    "production": "Production",
    "annual_rainfall": "Annual_Rainfall",
    "fertilizer": "Fertilizer",
    "pesticide": "Pesticide",
    "yield": "Yield",          # in case yield already exists
}

CATEGORICAL_COLS = ["State_Name", "District_Name", "Season", "Crop"]
NUMERIC_COLS = ["Crop_Year", "Area"]        # Production excluded — it encodes target
OPTIONAL_NUMERIC = ["Annual_Rainfall", "Fertilizer", "Pesticide"]

TARGET_COL = "Yield_tonnes_per_ha"
TRAIN_YEARS_MAX = 2013          # up to and including 2013 → train
YIELD_UPPER_PERCENTILE = 99.5   # clip extreme outliers at 99.5th percentile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map actual column names to canonical names via COL_MAP."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    renames = {}
    for col in df.columns:
        canonical = COL_MAP.get(col.lower().replace(" ", "_"))
        if canonical and col != canonical:
            renames[col] = canonical
    return df.rename(columns=renames)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(raw_path: Path = RAW_PATH, out_dir: Path = OUT_DIR) -> dict:
    """
    Execute the full preprocessing pipeline.
    Returns a summary dict with artefact paths and statistics.
    """
    # ── 1. Load ──────────────────────────────────────────────────────
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Raw CSV not found: {raw_path}\n"
            "Run: python src/download_datasets.py"
        )
    df = pd.read_csv(raw_path, low_memory=False)
    print(f"[crop_yield] Loaded  : {len(df):,} rows × {len(df.columns)} cols")

    df = _normalise_columns(df)
    print(f"[crop_yield] Columns : {list(df.columns)}")

    # Check mandatory columns
    mandatory = ["Crop_Year", "Area", "Production", "State_Name", "Season", "Crop"]
    missing_cols = [c for c in mandatory if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing mandatory columns: {missing_cols}")

    # ── 2. Coerce types ───────────────────────────────────────────────
    df["Area"] = pd.to_numeric(df["Area"], errors="coerce")
    df["Production"] = pd.to_numeric(df["Production"], errors="coerce")
    df["Crop_Year"] = pd.to_numeric(df["Crop_Year"], errors="coerce")

    # ── 3. Derive target: Yield = Production / Area ───────────────────
    n_zero_area = (df["Area"] == 0).sum()
    n_null_prod = df["Production"].isna().sum()
    print(f"[crop_yield] Zero-area rows : {n_zero_area:,}  |  Null Production : {n_null_prod:,}")

    # Replace zero area with NaN to avoid division by zero
    df["Area"] = df["Area"].replace(0, np.nan)
    df[TARGET_COL] = df["Production"] / df["Area"]

    # ── 4. Drop invalid rows ──────────────────────────────────────────
    n_before = len(df)
    df = df.dropna(subset=[TARGET_COL, "Area", "Production", "Crop_Year"])
    df = df[df[TARGET_COL] > 0]
    n_dropped = n_before - len(df)
    print(f"[crop_yield] Dropped {n_dropped:,} rows (null/zero target)")

    # Clip extreme outliers
    yield_cap = float(df[TARGET_COL].quantile(YIELD_UPPER_PERCENTILE / 100))
    n_extreme = (df[TARGET_COL] > yield_cap).sum()
    if n_extreme:
        print(f"[crop_yield] Clipping {n_extreme:,} extreme yield rows > {yield_cap:.2f} t/ha")
        df = df[df[TARGET_COL] <= yield_cap].copy()

    print(f"[crop_yield] Clean rows : {len(df):,}")
    print(f"[crop_yield] Yield range: {df[TARGET_COL].min():.3f} – {df[TARGET_COL].max():.3f} t/ha")
    print(f"[crop_yield] Yield mean : {df[TARGET_COL].mean():.3f} t/ha")

    # ── 5. Determine available feature columns ────────────────────────
    available_numeric = [c for c in NUMERIC_COLS if c in df.columns]
    for col in OPTIONAL_NUMERIC:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            # Fill optional numeric with median
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            available_numeric.append(col)
            print(f"[crop_yield] Optional column included: {col}")

    available_cats = [c for c in CATEGORICAL_COLS if c in df.columns]
    all_features = available_cats + available_numeric

    # ── 6. Clean categoricals ─────────────────────────────────────────
    for col in available_cats:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": "Unknown", "": "Unknown"})

    # ── 7. Temporal train/test split ──────────────────────────────────
    train_mask = df["Crop_Year"] <= TRAIN_YEARS_MAX
    test_mask = df["Crop_Year"] > TRAIN_YEARS_MAX
    df_train = df[train_mask].copy()
    df_test = df[test_mask].copy()

    if len(df_test) == 0:
        print("[crop_yield] ⚠ No test rows after temporal split — using random 20% fallback")
        from sklearn.model_selection import train_test_split
        df_train, df_test = train_test_split(df, test_size=0.20, random_state=42)
        df_train = df_train.copy()
        df_test = df_test.copy()

    print(f"[crop_yield] Train (≤{TRAIN_YEARS_MAX}) : {len(df_train):,} rows")
    print(f"[crop_yield] Test  (>{TRAIN_YEARS_MAX}) : {len(df_test):,} rows")

    # ── 8. Encode categoricals (fit on train) ─────────────────────────
    cat_encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    df_train[available_cats] = cat_encoder.fit_transform(df_train[available_cats])
    df_test[available_cats] = cat_encoder.transform(df_test[available_cats])

    # ── 9. Scale numeric features (fit on train) ──────────────────────
    scaler = StandardScaler()
    df_train[available_numeric] = scaler.fit_transform(df_train[available_numeric])
    df_test[available_numeric] = scaler.transform(df_test[available_numeric])

    # ── 10. Log-transform target (improves regression on skewed data) ──
    df_train["log_yield"] = np.log1p(df_train[TARGET_COL])
    df_test["log_yield"] = np.log1p(df_test[TARGET_COL])

    # ── 11. Save artefacts ────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    feature_cols_out = all_features + [TARGET_COL, "log_yield"]

    train_out = df_train[feature_cols_out]
    test_out = df_test[feature_cols_out]

    train_path = out_dir / "train.csv"
    test_path = out_dir / "test.csv"
    train_out.to_csv(train_path, index=False)
    test_out.to_csv(test_path, index=False)

    scaler_path = out_dir / "scaler.joblib"
    cat_enc_path = out_dir / "categorical_encoder.joblib"
    meta_path = out_dir / "feature_meta.json"

    joblib.dump(scaler, scaler_path)
    joblib.dump(cat_encoder, cat_enc_path)

    meta = {
        "categorical_features": available_cats,
        "numeric_features": available_numeric,
        "all_features": all_features,
        "target": TARGET_COL,
        "log_target": "log_yield",
        "train_split": f"Crop_Year <= {TRAIN_YEARS_MAX}",
        "test_split": f"Crop_Year > {TRAIN_YEARS_MAX}",
        "yield_cap_percentile": YIELD_UPPER_PERCENTILE,
        "yield_cap_value": float(yield_cap),
        "note": (
            "Production column excluded from features — it directly encodes the target. "
            "log_yield (log1p-transformed) is recommended as training target; "
            "inverse transform with expm1() to recover tonnes/ha."
        ),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    _rel_out = str(out_dir.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in out_dir.parents or out_dir == PROJECT_ROOT else str(out_dir)
    print(f"[crop_yield] Saved to : {_rel_out}/")

    return {
        "dataset": "crop_yield_india",
        "clean_rows": len(df),
        "train_rows": len(df_train),
        "test_rows": len(df_test),
        "features": all_features,
        "target": TARGET_COL,
        "log_target": "log_yield",
        "train_csv": str(train_path),
        "test_csv": str(test_path),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        summary = run()
        print("\nSummary:")
        for k, v in summary.items():
            print(f"  {k:<22}: {v}")
    except FileNotFoundError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
