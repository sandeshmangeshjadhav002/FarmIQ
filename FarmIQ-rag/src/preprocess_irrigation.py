"""
FarmIQ-ML — Irrigation Prediction Preprocessing
=================================================
Primary dataset:
  GCEKIoTCommunity/Irrigation-Dataset (GitHub)
  Academic source: CSE Depts, GCE Kalahandi & PMEC Berhampur,
  Supported by MHRD-NPIU, Government of India.
  Columns: CropType, CropDays, SoilMoisture, SoilTemperature,
           Temperature, Humidity, Irrigation (Y/N → 1/0)

Alternate dataset (if primary is unavailable):
  Mendeley DOI: 10.17632/fpdwmm7nrb.1
  Columns: Soil_Moisture, Temperature, Humidity, Motor_Status (1/0)
  This dataset lacks crop context but is valid for binary classification.

Task: Binary classification — irrigate (1) or not (0)

IMPORTANT NOTE on dataset availability:
  No public direct-download URL exists for the GCEKIoT dataset.
  The Mendeley dataset requires a free account.
  This preprocessor handles both formats transparently.

Pipeline:
  1. Load raw CSV (auto-detect primary or alternate format)
  2. Normalise column names
  3. Validate and clip numeric ranges
  4. Drop duplicates and null targets
  5. Encode target (0/1)
  6. Encode CropType (if present)
  7. Scale numeric features
  8. Stratified 80/20 split
  9. Save artefacts

Rule-based baseline (for cases where data is unavailable):
  IF SoilMoisture < 30% THEN irrigate = 1 ELSE irrigate = 0
  This is documented as the baseline and should be beaten by the ML model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

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
RAW_PATH = PROJECT_ROOT / "datasets" / "raw" / "irrigation" / "irrigation_dataset.csv"
OUT_DIR = PROJECT_ROOT / "datasets" / "processed" / "irrigation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RANDOM_STATE = 42
TEST_SIZE = 0.20

# Primary dataset (GCEKIoT) column specs
PRIMARY_COLS = {
    "croptype": "CropType",
    "cropdays": "CropDays",
    "soilmoisture": "SoilMoisture",
    "soiltemperature": "SoilTemperature",
    "temperature": "Temperature",
    "humidity": "Humidity",
    "irrigation": "Irrigation",
    "irrigation(y/n)": "Irrigation",
}

# Alternate dataset (Mendeley) column specs
ALTERNATE_COLS = {
    "soil_moisture": "SoilMoisture",
    "soil moisture": "SoilMoisture",
    "air_temperature": "Temperature",
    "air temperature": "Temperature",
    "temperature": "Temperature",
    "humidity": "Humidity",
    "motor_status": "Irrigation",
    "motor status": "Irrigation",
    "motor on/off": "Irrigation",
}

VALID_RANGES = {
    # SoilMoisture is raw capacitive sensor reading (0–2000), not percentage
    "SoilMoisture": (0.0, 2000.0),
    "SoilTemperature": (0.0, 60.0),
    "Temperature": (0.0, 60.0),
    "Humidity": (0.0, 100.0),
    "CropDays": (0.0, 365.0),
}

# Rule-based baseline threshold (documented)
RULE_BASED_MOISTURE_THRESHOLD = 30.0  # % — irrigate if SoilMoisture < 30%


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and map to canonical names."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    renames = {}
    for col in df.columns:
        key = col.lower().replace(" ", "").replace("_", "").replace("(", "").replace(")", "").replace("/", "")
        # Try primary map
        for raw_key, canonical in PRIMARY_COLS.items():
            norm_raw = raw_key.lower().replace(" ", "").replace("_", "").replace("(", "").replace(")", "").replace("/", "")
            if key == norm_raw:
                renames[col] = canonical
                break
        else:
            for raw_key, canonical in ALTERNATE_COLS.items():
                norm_raw = raw_key.lower().replace(" ", "").replace("_", "").replace("(", "").replace(")", "").replace("/", "")
                if key == norm_raw:
                    renames[col] = canonical
                    break
    return df.rename(columns=renames)


def _encode_target(series: pd.Series) -> pd.Series:
    """
    Convert Irrigation column to 0/1 integers.
    Handles: 1/0, 'Y'/'N', 'Yes'/'No', 'TRUE'/'FALSE', 'ON'/'OFF'.
    """
    s = series.copy()
    # Already numeric 0/1
    if pd.api.types.is_numeric_dtype(s):
        s = s.round().astype(int).clip(0, 1)
        return s
    # String mapping
    mapping = {
        "y": 1, "n": 0, "yes": 1, "no": 0,
        "1": 1, "0": 0, "true": 1, "false": 0,
        "on": 1, "off": 0,
    }
    return s.astype(str).str.strip().str.lower().map(mapping)


def _generate_rule_based_baseline(out_dir: Path) -> None:
    """Write the rule-based baseline specification to a JSON file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = {
        "name": "Rule-Based Irrigation Baseline",
        "description": (
            "A transparent, agriculturally grounded baseline for irrigation prediction. "
            "Based on the widely accepted agronomic principle that irrigation is triggered "
            "when available soil moisture falls below the field capacity threshold."
        ),
        "rule": "IF SoilMoisture < {threshold}% THEN irrigate=1 ELSE irrigate=0".format(
            threshold=RULE_BASED_MOISTURE_THRESHOLD
        ),
        "threshold_pct": RULE_BASED_MOISTURE_THRESHOLD,
        "rationale": (
            "Soil moisture below 30% of field capacity is a common trigger for irrigation "
            "in Indian Kharif and Rabi crops (source: ICAR guidelines). "
            "This baseline should be exceeded by any trained ML model."
        ),
        "python_implementation": (
            "def rule_based_irrigate(soil_moisture_pct):\n"
            "    return 1 if soil_moisture_pct < 30.0 else 0"
        ),
    }
    path = out_dir / "rule_based_baseline.json"
    with open(path, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"[irrigation] Rule-based baseline saved: {path.name}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(raw_path: Path = RAW_PATH, out_dir: Path = OUT_DIR) -> dict:
    """
    Execute the full preprocessing pipeline.
    Returns a summary dict. Generates rule-based baseline regardless of data.
    """
    # Always write the rule-based baseline
    _generate_rule_based_baseline(out_dir)

    # ── 1. Load ──────────────────────────────────────────────────────
    if not raw_path.exists():
        print(
            "[irrigation] ✗ Raw CSV not found.\n"
            "  Primary source   : https://github.com/GCEKIoTCommunity/Irrigation-Dataset\n"
            "  Alternate source : https://data.mendeley.com/datasets/fpdwmm7nrb/1\n"
            "  After downloading, save as:\n"
            f"  {raw_path}\n"
            "  Then re-run this script.\n"
            "\n  Rule-based baseline has been saved and can be used until real data is available."
        )
        return {
            "dataset": "irrigation",
            "status": "missing",
            "rule_based_baseline": str(out_dir / "rule_based_baseline.json"),
        }

    df = pd.read_csv(raw_path, low_memory=False)
    print(f"[irrigation] Loaded  : {len(df):,} rows × {len(df.columns)} cols")
    print(f"[irrigation] Columns : {list(df.columns)}")

    # ── 2. Normalise columns ──────────────────────────────────────────
    df = _normalise_columns(df)
    print(f"[irrigation] Normalised columns: {list(df.columns)}")

    if "Irrigation" not in df.columns:
        raise ValueError(
            "Target column 'Irrigation' not found after normalisation.\n"
            f"Detected columns: {list(df.columns)}\n"
            "This dataset may lack a supervised target — consider the rule-based baseline."
        )

    # ── 3. Encode target ──────────────────────────────────────────────
    df["Irrigation"] = _encode_target(df["Irrigation"])
    null_target = df["Irrigation"].isna().sum()
    if null_target:
        df = df[df["Irrigation"].notna()].copy()
        print(f"[irrigation] Dropped {null_target} rows with unrecognised target values")

    df["Irrigation"] = df["Irrigation"].astype(int)

    # Check target distribution
    vc = df["Irrigation"].value_counts()
    print(f"[irrigation] Target distribution: {dict(vc)}")
    if len(vc) < 2:
        print("[irrigation] ⚠ Only one class in target — dataset may not support supervised training")

    # ── 4. Drop duplicates ────────────────────────────────────────────
    n_before = len(df)
    df = df.drop_duplicates()
    n_dupes = n_before - len(df)
    if n_dupes:
        print(f"[irrigation] Dropped : {n_dupes:,} duplicate rows")

    # ── 5. Determine available feature columns ────────────────────────
    numeric_features = [c for c in ["SoilMoisture", "SoilTemperature", "Temperature", "Humidity", "CropDays"]
                        if c in df.columns]
    cat_features = [c for c in ["CropType"] if c in df.columns]
    all_features = numeric_features + cat_features

    if not numeric_features:
        raise ValueError("No recognisable numeric feature columns found. Check column mapping.")

    # ── 6. Clip numeric ranges ────────────────────────────────────────
    for col in numeric_features:
        if col in VALID_RANGES:
            lo, hi = VALID_RANGES[col]
            df[col] = pd.to_numeric(df[col], errors="coerce")
            n_bad = ((df[col] < lo) | (df[col] > hi)).sum()
            if n_bad:
                print(f"[irrigation] ⚠ {col}: {n_bad} out-of-range → clipping")
                df[col] = df[col].clip(lo, hi)

    # Fill missing numerics with median
    for col in numeric_features:
        cnt = df[col].isna().sum()
        if cnt:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            print(f"[irrigation] {col}: {cnt} nulls → median ({median_val:.4f})")

    # ── 7. Encode CropType ────────────────────────────────────────────
    if "CropType" in df.columns:
        df["CropType"] = df["CropType"].astype(str).str.strip()

    # ── 8. Stratified split ───────────────────────────────────────────
    X = df[all_features].copy()
    y = df["Irrigation"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"[irrigation] Train : {len(X_train):,}  |  Test : {len(X_test):,}")

    # ── 9. Encode CropType (fit on train) ─────────────────────────────
    crop_le = None
    if "CropType" in X_train.columns:
        crop_le = LabelEncoder()
        X_train["CropType"] = crop_le.fit_transform(X_train["CropType"])
        # Handle unseen crop types in test
        known_classes = set(crop_le.classes_)
        X_test["CropType"] = X_test["CropType"].apply(
            lambda x: x if x in known_classes else crop_le.classes_[0]
        )
        X_test["CropType"] = crop_le.transform(X_test["CropType"])

    # ── 10. Scale numeric (fit on train) ──────────────────────────────
    scaler = StandardScaler()
    X_train[numeric_features] = scaler.fit_transform(X_train[numeric_features])
    X_test[numeric_features] = scaler.transform(X_test[numeric_features])

    # ── 11. Save ──────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    train_df = X_train.copy()
    train_df["Irrigation"] = y_train
    test_df = X_test.copy()
    test_df["Irrigation"] = y_test

    train_path = out_dir / "train.csv"
    test_path = out_dir / "test.csv"
    train_df.to_csv(train_path, index=False)
    test_df.to_csv(test_path, index=False)

    scaler_path = out_dir / "scaler.joblib"
    joblib.dump(scaler, scaler_path)

    if crop_le:
        crop_enc_path = out_dir / "crop_encoder.joblib"
        joblib.dump(crop_le, crop_enc_path)

    meta_path = out_dir / "feature_meta.json"
    meta = {
        "numeric_features": numeric_features,
        "categorical_features": cat_features,
        "all_features": all_features,
        "target": "Irrigation",
        "target_encoding": {"0": "No irrigation", "1": "Irrigate"},
        "source_primary": "https://github.com/GCEKIoTCommunity/Irrigation-Dataset",
        "source_alternate": "https://data.mendeley.com/datasets/fpdwmm7nrb/1",
        "rule_based_baseline": (
            "IF SoilMoisture < 30% THEN 1 ELSE 0  "
            "(ICAR-aligned agronomic threshold)"
        ),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    _rel_out = str(out_dir.relative_to(PROJECT_ROOT)) if PROJECT_ROOT in out_dir.parents or out_dir == PROJECT_ROOT else str(out_dir)
    print(f"[irrigation] Saved to : {_rel_out}/")

    return {
        "dataset": "irrigation",
        "status": "ok",
        "clean_rows": len(df),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "features": all_features,
        "target": "Irrigation",
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
    except (FileNotFoundError, ValueError) as e:
        print(f"\n✗ {e}")
        sys.exit(1)
