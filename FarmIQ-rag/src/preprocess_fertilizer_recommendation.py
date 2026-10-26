"""
FarmIQ-ML — Fertilizer Recommendation Preprocessing
=====================================================
Dataset : Kaggle — gdabhishek/fertilizer-prediction
Task    : Multi-class classification (7 fertilizer types)
Columns : Temparature, Humidity, Moisture, Soil Type, Crop Type,
          Nitrogen, Potassium, Phosphorous → Fertilizer Name

Fertilizer labels (as documented by the dataset):
  Urea, DAP, 14-35-14, 28-28, 17-17-17, 20-20, 10-26-26
These are real commercial fertilizer grades, suitable for classification.

Pipeline:
  1. Load raw CSV
  2. Validate and normalise column names
  3. Remove duplicates
  4. Handle missing values
  5. Validate numeric ranges
  6. Encode categoricals (OrdinalEncoder for soil/crop type)
  7. Encode target (LabelEncoder)
  8. Scale numeric features (StandardScaler)
  9. Stratified train/test split (80/20)
  10. Save processed artefacts

No data leakage: encoders and scaler fit on training data only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder, StandardScaler
import joblib

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠→)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = (
    PROJECT_ROOT / "datasets" / "raw" / "fertilizer_recommendation" / "Fertilizer Prediction.csv"
)
OUT_DIR = PROJECT_ROOT / "datasets" / "processed" / "fertilizer_recommendation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Canonical column names (after normalisation)
NUMERIC_COLS = ["Temparature", "Humidity", "Moisture", "Nitrogen", "Potassium", "Phosphorous"]
CATEGORICAL_COLS = ["Soil Type", "Crop Type"]
TARGET_COL = "Fertilizer Name"
ALL_FEATURE_COLS = NUMERIC_COLS + CATEGORICAL_COLS
RANDOM_STATE = 42
TEST_SIZE = 0.20

VALID_RANGES: dict[str, tuple[float, float]] = {
    "Temparature": (0.0, 55.0),
    "Humidity": (0.0, 100.0),
    "Moisture": (0.0, 100.0),
    "Nitrogen": (0.0, 200.0),
    "Potassium": (0.0, 250.0),
    "Phosphorous": (0.0, 200.0),
}

# Known soil and crop types from the dataset (used for unseen-category handling)
KNOWN_SOIL_TYPES = [
    "Sandy", "Loamy", "Black", "Red", "Clayey",
    "Sandy loam", "Loamy sand", "Clay loam", "Silty clay",
]
KNOWN_CROP_TYPES = [
    "Wheat", "Maize", "Sugarcane", "Cotton", "Tobacco",
    "Paddy", "Barley", "Oil seeds", "Pulses", "Ground Nuts",
    "Millets", "Ground Nut",
]


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip whitespace from column names and attempt fuzzy matching
    for known minor variations (e.g. 'Fertilizer_Name' → 'Fertilizer Name').
    """
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # Handle common alternative spellings
    renames: dict[str, str] = {}
    for col in df.columns:
        col_lower = col.lower().replace("_", " ")
        if col_lower == "fertilizer name":
            renames[col] = "Fertilizer Name"
        elif col_lower == "fertilizer":
            renames[col] = "Fertilizer Name"
        elif col_lower == "soil type":
            renames[col] = "Soil Type"
        elif col_lower == "crop type":
            renames[col] = "Crop Type"
        elif col_lower in ("temparature", "temperature"):
            renames[col] = "Temparature"  # keep the original dataset's typo
        elif col_lower == "humidity":
            renames[col] = "Humidity"
        elif col_lower == "moisture":
            renames[col] = "Moisture"
        elif col_lower in ("nitrogen", "n"):
            renames[col] = "Nitrogen"
        elif col_lower in ("potassium", "k"):
            renames[col] = "Potassium"
        elif col_lower in ("phosphorous", "phosphorus", "p"):
            renames[col] = "Phosphorous"
    if renames:
        df = df.rename(columns=renames)
    return df


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
    df = pd.read_csv(raw_path)
    print(f"[fertilizer] Loaded  : {len(df):,} rows × {len(df.columns)} cols")
    print(f"[fertilizer] Columns : {list(df.columns)}")

    # ── 2. Normalise columns ──────────────────────────────────────────
    df = _normalise_columns(df)

    required = ALL_FEATURE_COLS + [TARGET_COL]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Missing expected columns after normalisation: {missing_cols}\n"
            f"Found: {list(df.columns)}"
        )

    # ── 3. Drop duplicates ────────────────────────────────────────────
    n_before = len(df)
    df = df.drop_duplicates()
    n_dupes = n_before - len(df)
    if n_dupes:
        print(f"[fertilizer] Dropped  : {n_dupes:,} duplicate rows")

    # ── 4. Handle missing values ──────────────────────────────────────
    for col in NUMERIC_COLS:
        cnt = df[col].isnull().sum()
        if cnt:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            print(f"[fertilizer] {col}: {cnt} nulls → median ({median_val:.4f})")

    for col in CATEGORICAL_COLS:
        cnt = df[col].isnull().sum()
        if cnt:
            mode_val = df[col].mode().iloc[0]
            df[col] = df[col].fillna(mode_val)
            print(f"[fertilizer] {col}: {cnt} nulls → mode ('{mode_val}')")

    missing_target = df[TARGET_COL].isnull().sum()
    if missing_target:
        df = df[df[TARGET_COL].notna()].copy()
        print(f"[fertilizer] Dropped {missing_target} rows with null target")

    # ── 5. Range validation ───────────────────────────────────────────
    for col, (lo, hi) in VALID_RANGES.items():
        if col in df.columns:
            n_bad = ((df[col] < lo) | (df[col] > hi)).sum()
            if n_bad:
                print(f"[fertilizer] ⚠ {col}: {n_bad} out-of-range → clipping to [{lo},{hi}]")
                df[col] = df[col].clip(lo, hi)

    # ── 6. Encode target ──────────────────────────────────────────────
    target_le = LabelEncoder()
    df["fertilizer_encoded"] = target_le.fit_transform(df[TARGET_COL])
    fertilizer_map = {int(i): str(c) for i, c in enumerate(target_le.classes_)}
    print(f"[fertilizer] Classes : {list(target_le.classes_)}")

    # ── 7. Stratified split (before encoding cats to avoid leakage) ───
    X = df[ALL_FEATURE_COLS].copy()
    y = df["fertilizer_encoded"].values

    # Drop classes with fewer than 2 samples (can't stratify)
    class_counts = pd.Series(y).value_counts()
    small_classes = class_counts[class_counts < 2].index.tolist()
    if small_classes:
        small_names = [target_le.classes_[i] for i in small_classes]
        print(f"[fertilizer] ⚠ Dropping {len(small_classes)} class(es) with <2 samples: {small_names}")
        mask = ~pd.Series(y).isin(small_classes).values
        X = X[mask]
        y = y[mask]
        # Re-encode target after dropping classes
        target_le2 = LabelEncoder()
        y = target_le2.fit_transform(target_le.inverse_transform(y))
        target_le = target_le2
        fertilizer_map = {int(i): str(c) for i, c in enumerate(target_le.classes_)}
        df = df[mask].copy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"[fertilizer] Train : {len(X_train):,}  |  Test : {len(X_test):,}")

    # ── 8. Encode categoricals (fit on train only) ────────────────────
    # Strip and title-case categorical values for consistency
    for col in CATEGORICAL_COLS:
        X_train[col] = X_train[col].astype(str).str.strip().str.title()
        X_test[col] = X_test[col].astype(str).str.strip().str.title()

    cat_encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    X_train[CATEGORICAL_COLS] = cat_encoder.fit_transform(X_train[CATEGORICAL_COLS])
    X_test[CATEGORICAL_COLS] = cat_encoder.transform(X_test[CATEGORICAL_COLS])

    # ── 9. Scale numeric features (fit on train only) ─────────────────
    scaler = StandardScaler()
    X_train[NUMERIC_COLS] = scaler.fit_transform(X_train[NUMERIC_COLS])
    X_test[NUMERIC_COLS] = scaler.transform(X_test[NUMERIC_COLS])

    # ── 10. Save ──────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    train_df = X_train.copy()
    train_df["fertilizer_encoded"] = y_train
    test_df = X_test.copy()
    test_df["fertilizer_encoded"] = y_test

    train_path = out_dir / "train.csv"
    test_path = out_dir / "test.csv"
    train_df.to_csv(train_path, index=False)
    test_df.to_csv(test_path, index=False)

    scaler_path = out_dir / "scaler.joblib"
    cat_enc_path = out_dir / "categorical_encoder.joblib"
    target_enc_path = out_dir / "target_encoder.joblib"
    fert_map_path = out_dir / "fertilizer_map.json"

    joblib.dump(scaler, scaler_path)
    joblib.dump(cat_encoder, cat_enc_path)
    joblib.dump(target_le, target_enc_path)
    with open(fert_map_path, "w") as f:
        json.dump(fertilizer_map, f, indent=2)

    _rel_out = str(out_dir.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in out_dir.parents or out_dir == PROJECT_ROOT else str(out_dir)
    print(f"[fertilizer] Saved to : {_rel_out}/")

    return {
        "dataset": "fertilizer_recommendation",
        "raw_rows": n_before,
        "clean_rows": len(df),
        "duplicates_removed": n_dupes,
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "n_classes": len(target_le.classes_),
        "features": ALL_FEATURE_COLS,
        "target": TARGET_COL,
        "fertilizer_map": fertilizer_map,
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
