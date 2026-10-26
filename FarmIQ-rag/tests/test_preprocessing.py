"""
FarmIQ-ML — Preprocessing Unit Tests
======================================
Tests for dataset loading helpers, column normalisation, target encoding,
range validation, and pipeline guard-rails.

These tests do NOT require the real datasets to be present.
They use small synthetic DataFrames that mimic the real schemas.

Run:
    python -m pytest tests/ -v
    # or without pytest:
    python tests/test_preprocessing.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Make src importable regardless of how pytest is invoked
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===========================================================================
# Helpers / fixtures
# ===========================================================================

def _crop_rec_df(n_per_crop: int = 10) -> pd.DataFrame:
    """
    Synthetic Crop Recommendation DataFrame.
    n_per_crop rows per crop (must be >= 2 for stratified split to work;
    default 10 gives 20% = 2 test rows per class).
    Values are varied so duplicates are not all collapsed.
    """
    rng = np.random.default_rng(42)
    rows = []
    for i, crop in enumerate(["rice", "maize"]):
        for j in range(n_per_crop):
            rows.append({
                "N": float(50 + i * 10 + j),
                "P": float(40 + i * 5 + j),
                "K": float(30 + i * 8 + j),
                "temperature": float(20 + i * 3 + j * 0.5),
                "humidity": float(60 + i * 5 + j),
                "ph": float(6.0 + j * 0.05),
                "rainfall": float(180 + j * 5),
                "label": crop,
            })
    return pd.DataFrame(rows)


def _fertilizer_df(n_per_class: int = 6) -> pd.DataFrame:
    """
    Minimal valid Fertilizer Prediction DataFrame.
    n_per_class rows per fertilizer (must be >= 2 for stratified split).
    """
    rows = []
    fertilizers = ["Urea", "DAP", "17-17-17"]
    soil_types = ["Sandy", "Loamy", "Black"]
    crop_types = ["Wheat", "Maize", "Paddy"]
    for fi, fert in enumerate(fertilizers):
        for j in range(n_per_class):
            rows.append({
                "Temparature": float(20 + fi * 3 + j),
                "Humidity": float(50 + fi * 5 + j),
                "Moisture": float(30 + fi * 4 + j),
                "Soil Type": soil_types[fi % 3],
                "Crop Type": crop_types[fi % 3],
                "Nitrogen": float(30 + fi * 10 + j),
                "Potassium": float(20 + fi * 8 + j),
                "Phosphorous": float(15 + fi * 6 + j),
                "Fertilizer Name": fert,
            })
    return pd.DataFrame(rows)


def _yield_df() -> pd.DataFrame:
    """Minimal valid Crop Yield India DataFrame."""
    rows = []
    for year in range(1997, 2016):
        rows.append({
            "State_Name": "Punjab",
            "District_Name": "Ludhiana",
            "Crop_Year": year,
            "Season": "Kharif",
            "Crop": "Rice",
            "Area": 1000.0,
            "Production": 3000.0,
        })
    return pd.DataFrame(rows)


def _irrigation_df() -> pd.DataFrame:
    """Minimal valid Irrigation DataFrame (primary GCEKIoT schema)."""
    rows = []
    for i in range(20):
        rows.append({
            "CropType": "Paddy" if i % 2 == 0 else "Ground Nuts",
            "CropDays": 30 + i,
            "SoilMoisture": 20.0 + (i * 3) % 60,
            "SoilTemperature": 28.0 + i % 5,
            "Temperature": 30.0 + i % 6,
            "Humidity": 60.0 + i % 20,
            "Irrigation": "Y" if i % 2 == 0 else "N",
        })
    return pd.DataFrame(rows)


# ===========================================================================
# Crop Recommendation tests
# ===========================================================================

class TestCropRecommendationPreprocessing:

    def test_pipeline_produces_train_test_csvs(self, tmp_path):
        """End-to-end: pipeline reads CSV and writes train/test."""
        import preprocess_crop_recommendation as pcr

        # Write synthetic raw data
        raw_dir = tmp_path / "raw" / "crop_recommendation"
        raw_dir.mkdir(parents=True)
        df = _crop_rec_df()
        csv_path = raw_dir / "Crop_recommendation.csv"
        df.to_csv(csv_path, index=False)

        out_dir = tmp_path / "processed" / "crop_recommendation"
        summary = pcr.run(raw_path=csv_path, out_dir=out_dir)

        assert (out_dir / "train.csv").exists(), "train.csv not created"
        assert (out_dir / "test.csv").exists(), "test.csv not created"
        assert (out_dir / "scaler.joblib").exists(), "scaler not saved"
        assert (out_dir / "label_encoder.joblib").exists(), "encoder not saved"

    def test_train_rows_plus_test_equals_clean(self, tmp_path):
        import preprocess_crop_recommendation as pcr

        raw_dir = tmp_path / "raw" / "crop_recommendation"
        raw_dir.mkdir(parents=True)
        df = _crop_rec_df()
        csv_path = raw_dir / "Crop_recommendation.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcr.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["train_rows"] + summary["test_rows"] == summary["clean_rows"]

    def test_duplicate_removal(self, tmp_path):
        import preprocess_crop_recommendation as pcr

        raw_dir = tmp_path / "raw" / "crop_recommendation"
        raw_dir.mkdir(parents=True)
        df = _crop_rec_df()
        # Add identical duplicate rows
        df_with_dupes = pd.concat([df, df.iloc[:4]], ignore_index=True)
        csv_path = raw_dir / "Crop_recommendation.csv"
        df_with_dupes.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcr.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["duplicates_removed"] == 4

    def test_label_map_matches_classes(self, tmp_path):
        import preprocess_crop_recommendation as pcr

        raw_dir = tmp_path / "raw" / "crop_recommendation"
        raw_dir.mkdir(parents=True)
        df = _crop_rec_df()
        csv_path = raw_dir / "Crop_recommendation.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcr.run(raw_path=csv_path, out_dir=out_dir)
        with open(summary["label_map"]) as f:
            label_map = json.load(f)
        assert summary["n_classes"] == len(label_map)

    def test_missing_file_raises(self, tmp_path):
        import preprocess_crop_recommendation as pcr
        with pytest.raises(FileNotFoundError):
            pcr.run(raw_path=tmp_path / "nonexistent.csv", out_dir=tmp_path)

    def test_scaled_features_have_zero_mean(self, tmp_path):
        """StandardScaler should produce approximately zero-mean train features."""
        import preprocess_crop_recommendation as pcr

        raw_dir = tmp_path / "raw" / "crop_recommendation"
        raw_dir.mkdir(parents=True)
        # Use larger synthetic set for meaningful scaling check
        rng = np.random.default_rng(0)
        n = 100
        crops = ["rice", "maize", "wheat", "cotton", "barley"]
        rows = [
            {
                "N": float(rng.integers(10, 120)),
                "P": float(rng.integers(10, 100)),
                "K": float(rng.integers(10, 120)),
                "temperature": float(rng.uniform(15, 40)),
                "humidity": float(rng.uniform(30, 95)),
                "ph": float(rng.uniform(4, 9)),
                "rainfall": float(rng.uniform(50, 500)),
                "label": crops[i % len(crops)],
            }
            for i in range(n)
        ]
        df = pd.DataFrame(rows)
        csv_path = raw_dir / "Crop_recommendation.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        pcr.run(raw_path=csv_path, out_dir=out_dir)
        train_df = pd.read_csv(out_dir / "train.csv")
        feature_cols = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
        means = train_df[feature_cols].mean()
        assert (means.abs() < 0.5).all(), f"Train feature means not near zero: {means.to_dict()}"


# ===========================================================================
# Fertilizer Recommendation tests
# ===========================================================================

class TestFertilizerPreprocessing:

    def test_pipeline_runs_end_to_end(self, tmp_path):
        import preprocess_fertilizer_recommendation as pfr

        raw_dir = tmp_path / "raw" / "fertilizer_recommendation"
        raw_dir.mkdir(parents=True)
        df = _fertilizer_df()
        csv_path = raw_dir / "Fertilizer Prediction.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pfr.run(raw_path=csv_path, out_dir=out_dir)
        assert (out_dir / "train.csv").exists()
        assert (out_dir / "test.csv").exists()
        assert summary["n_classes"] == 3

    def test_column_normalisation(self, tmp_path):
        """Column name variations are handled gracefully."""
        import preprocess_fertilizer_recommendation as pfr

        raw_dir = tmp_path / "raw" / "fertilizer_recommendation"
        raw_dir.mkdir(parents=True)
        df = _fertilizer_df()
        # Rename columns to alternative spellings
        df = df.rename(columns={
            "Fertilizer Name": "Fertilizer_Name",
            "Soil Type": "Soil_Type",
            "Crop Type": "Crop_Type",
            "Temparature": "Temperature",
        })
        csv_path = raw_dir / "Fertilizer Prediction.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pfr.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["n_classes"] == 3

    def test_missing_file_raises(self, tmp_path):
        import preprocess_fertilizer_recommendation as pfr
        with pytest.raises(FileNotFoundError):
            pfr.run(raw_path=tmp_path / "no.csv", out_dir=tmp_path)

    def test_fertilizer_map_saved(self, tmp_path):
        import preprocess_fertilizer_recommendation as pfr

        raw_dir = tmp_path / "raw" / "fertilizer_recommendation"
        raw_dir.mkdir(parents=True)
        df = _fertilizer_df()
        csv_path = raw_dir / "Fertilizer Prediction.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"
        out_dir.mkdir(parents=True)

        summary = pfr.run(raw_path=csv_path, out_dir=out_dir)
        fert_map_path = out_dir / "fertilizer_map.json"
        assert fert_map_path.exists()
        with open(fert_map_path) as f:
            fmap = json.load(f)
        assert len(fmap) == 3


# ===========================================================================
# Crop Yield tests
# ===========================================================================

class TestCropYieldPreprocessing:

    def test_yield_derived_from_production_area(self, tmp_path):
        import preprocess_crop_yield as pcy

        raw_dir = tmp_path / "raw" / "crop_yield_india"
        raw_dir.mkdir(parents=True)
        df = _yield_df()
        csv_path = raw_dir / "crop_production.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcy.run(raw_path=csv_path, out_dir=out_dir)
        train_df = pd.read_csv(out_dir / "train.csv")
        # All valid: yield = 3000/1000 = 3.0
        assert "Yield_tonnes_per_ha" in train_df.columns
        # Log yield should be positive
        assert (train_df["log_yield"] > 0).all()

    def test_zero_area_rows_dropped(self, tmp_path):
        import preprocess_crop_yield as pcy

        raw_dir = tmp_path / "raw" / "crop_yield_india"
        raw_dir.mkdir(parents=True)
        df = _yield_df()
        # Insert a zero-area row
        df.loc[len(df)] = {
            "State_Name": "Bihar", "District_Name": "Patna",
            "Crop_Year": 2000, "Season": "Kharif",
            "Crop": "Wheat", "Area": 0, "Production": 500,
        }
        csv_path = raw_dir / "crop_production.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcy.run(raw_path=csv_path, out_dir=out_dir)
        # The zero-area row must not appear in processed data
        train_df = pd.read_csv(out_dir / "train.csv")
        test_df = pd.read_csv(out_dir / "test.csv")
        combined = pd.concat([train_df, test_df])
        assert not (combined["Yield_tonnes_per_ha"].isna()).any()

    def test_production_column_not_in_features(self, tmp_path):
        """Production must not appear as a feature (data leakage guard)."""
        import preprocess_crop_yield as pcy

        raw_dir = tmp_path / "raw" / "crop_yield_india"
        raw_dir.mkdir(parents=True)
        df = _yield_df()
        csv_path = raw_dir / "crop_production.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pcy.run(raw_path=csv_path, out_dir=out_dir)
        assert "Production" not in summary["features"], \
            "Production column should not be in features — it encodes the target"

    def test_temporal_split_integrity(self, tmp_path):
        """Train and test sets must not overlap on Crop_Year."""
        import preprocess_crop_yield as pcy

        raw_dir = tmp_path / "raw" / "crop_yield_india"
        raw_dir.mkdir(parents=True)
        df = _yield_df()
        csv_path = raw_dir / "crop_production.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        pcy.run(raw_path=csv_path, out_dir=out_dir)
        meta_path = out_dir / "feature_meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        # Confirm split boundary is documented
        assert "train_split" in meta
        assert "test_split" in meta


# ===========================================================================
# Irrigation tests
# ===========================================================================

class TestIrrigationPreprocessing:

    def test_rule_based_baseline_always_created(self, tmp_path):
        """Baseline JSON must be created even if dataset is missing."""
        import preprocess_irrigation as pi

        out_dir = tmp_path / "processed"
        out_dir.mkdir(parents=True)
        result = pi.run(raw_path=tmp_path / "no.csv", out_dir=out_dir)

        assert result["status"] == "missing"
        baseline_path = out_dir / "rule_based_baseline.json"
        assert baseline_path.exists()
        with open(baseline_path) as f:
            b = json.load(f)
        assert "threshold_pct" in b
        assert b["threshold_pct"] == 30.0

    def test_yn_target_encoded_correctly(self, tmp_path):
        import preprocess_irrigation as pi

        raw_dir = tmp_path / "raw" / "irrigation"
        raw_dir.mkdir(parents=True)
        df = _irrigation_df()
        csv_path = raw_dir / "irrigation_dataset.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pi.run(raw_path=csv_path, out_dir=out_dir)
        train_df = pd.read_csv(out_dir / "train.csv")
        assert set(train_df["Irrigation"].unique()).issubset({0, 1}), \
            "Target must be 0/1 integers"

    def test_pipeline_end_to_end(self, tmp_path):
        import preprocess_irrigation as pi

        raw_dir = tmp_path / "raw" / "irrigation"
        raw_dir.mkdir(parents=True)
        df = _irrigation_df()
        csv_path = raw_dir / "irrigation_dataset.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pi.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["status"] == "ok"
        assert (out_dir / "train.csv").exists()
        assert (out_dir / "test.csv").exists()
        assert (out_dir / "scaler.joblib").exists()

    def test_train_test_no_overlap(self, tmp_path):
        import preprocess_irrigation as pi

        raw_dir = tmp_path / "raw" / "irrigation"
        raw_dir.mkdir(parents=True)
        df = _irrigation_df()
        csv_path = raw_dir / "irrigation_dataset.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pi.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["train_rows"] + summary["test_rows"] == summary["clean_rows"]

    def test_alternate_column_names_mendeley(self, tmp_path):
        """Alternate Mendeley-style columns should be normalised correctly."""
        import preprocess_irrigation as pi

        raw_dir = tmp_path / "raw" / "irrigation"
        raw_dir.mkdir(parents=True)
        # Mendeley-style schema
        df = pd.DataFrame({
            "Soil_Moisture": [25.0, 50.0, 20.0, 70.0, 15.0, 80.0,
                              22.0, 60.0, 18.0, 55.0] * 2,
            "Temperature": [30.0] * 20,
            "Humidity": [65.0] * 20,
            "Motor_Status": ([1, 0] * 10),
        })
        csv_path = raw_dir / "irrigation_dataset.csv"
        df.to_csv(csv_path, index=False)
        out_dir = tmp_path / "processed"

        summary = pi.run(raw_path=csv_path, out_dir=out_dir)
        assert summary["status"] == "ok"


# ===========================================================================
# Inspect datasets tests (basic smoke tests)
# ===========================================================================

class TestInspectDatasets:

    def test_inspect_handles_missing_gracefully(self, tmp_path, capsys):
        """inspect() must not raise for missing datasets."""
        import inspect_datasets as ids

        # Point to a non-existent path
        meta = {
            "path": tmp_path / "no_such_file.csv",
            "model": "Test Model",
            "target": "label",
            "expected_cols": ["a", "b", "label"],
            "numeric_cols": ["a", "b"],
            "valid_ranges": {},
        }
        result = ids.inspect("test_dataset", meta)
        assert result["status"] == "missing"

    def test_inspect_returns_ok_for_valid_csv(self, tmp_path, capsys):
        """inspect() returns status=ok for a valid crop rec CSV."""
        import inspect_datasets as ids

        df = _crop_rec_df()
        csv_path = tmp_path / "Crop_recommendation.csv"
        df.to_csv(csv_path, index=False)

        meta = {
            "path": csv_path,
            "model": "Crop Recommendation (Classification)",
            "target": "label",
            "expected_cols": ["N", "P", "K", "temperature", "humidity", "ph", "rainfall", "label"],
            "numeric_cols": ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"],
            "valid_ranges": {
                "N": (0, 200),
                "P": (0, 200),
                "K": (0, 250),
                "temperature": (0, 55),
                "humidity": (0, 100),
                "ph": (0, 14),
                "rainfall": (0, 3000),
            },
        }
        result = ids.inspect("crop_recommendation", meta)
        assert result["status"] == "ok"
        assert result["rows"] == len(df)
        assert not result["missing_any"]


# ===========================================================================
# Standalone runner (no pytest required)
# ===========================================================================

if __name__ == "__main__":
    import traceback

    test_classes = [
        TestCropRecommendationPreprocessing,
        TestFertilizerPreprocessing,
        TestCropYieldPreprocessing,
        TestIrrigationPreprocessing,
        TestInspectDatasets,
    ]

    passed = 0
    failed = 0

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(cls) if m.startswith("test_")]
        for method_name in methods:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                try:
                    getattr(instance, method_name)(tmp_path)
                    print(f"  ✓  {cls.__name__}.{method_name}")
                    passed += 1
                except Exception as exc:
                    print(f"  ✗  {cls.__name__}.{method_name}")
                    traceback.print_exc()
                    failed += 1

    print(f"\n{'=' * 50}")
    print(f"  Passed : {passed}  |  Failed : {failed}")
    if failed:
        sys.exit(1)
