"""
FarmIQ-ML — Dataset Inspector
==============================
Reads each raw dataset CSV, prints a quality report, and flags issues.
Missing datasets are reported without crashing.

Usage:
    python src/inspect_datasets.py
    python src/inspect_datasets.py --dataset crop_recommendation
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠→)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "datasets" / "raw"

# ---------------------------------------------------------------------------
# Dataset metadata
# ---------------------------------------------------------------------------
DATASET_META = {
    "crop_recommendation": {
        "path": RAW_DIR / "crop_recommendation" / "Crop_recommendation.csv",
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
    },
    "fertilizer_recommendation": {
        "path": RAW_DIR / "fertilizer_recommendation" / "Fertilizer Prediction.csv",
        "model": "Fertilizer Recommendation (Classification)",
        "target": "Fertilizer Name",
        "expected_cols": [
            "Temparature", "Humidity", "Moisture",
            "Soil Type", "Crop Type",
            "Nitrogen", "Potassium", "Phosphorous",
            "Fertilizer Name",
        ],
        "numeric_cols": ["Temparature", "Humidity", "Moisture", "Nitrogen", "Potassium", "Phosphorous"],
        "valid_ranges": {
            "Temparature": (0, 55),
            "Humidity": (0, 100),
            "Moisture": (0, 100),
            "Nitrogen": (0, 200),
            "Potassium": (0, 250),
            "Phosphorous": (0, 200),
        },
    },
    "crop_yield_india": {
        "path": RAW_DIR / "crop_yield_india" / "crop_production.csv",
        "model": "Crop Yield Prediction (Regression)",
        "target": "Yield_tonnes_per_ha",  # derived column
        "expected_cols": ["State_Name", "District_Name", "Crop_Year", "Season", "Crop", "Area", "Production"],
        "numeric_cols": ["Crop_Year", "Area", "Production"],
        "valid_ranges": {
            "Area": (0, 10_000_000),
            "Production": (0, 500_000_000),
            "Crop_Year": (1990, 2030),
        },
    },
    "irrigation": {
        "path": RAW_DIR / "irrigation" / "irrigation_dataset.csv",
        "model": "Irrigation Prediction (Binary Classification)",
        "target": "Irrigation",   # Y/N or 1/0
        "expected_cols": ["CropType", "CropDays", "SoilMoisture", "SoilTemperature",
                          "Temperature", "Humidity", "Irrigation"],
        "numeric_cols": ["CropDays", "SoilMoisture", "SoilTemperature", "Temperature", "Humidity"],
        "valid_ranges": {
            # SoilMoisture is raw capacitive sensor reading (0–2000), not percentage
            "SoilMoisture": (0, 2000),
            "SoilTemperature": (0, 60),
            "Temperature": (0, 60),
            "Humidity": (0, 100),
            "CropDays": (0, 365),
        },
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 65
THIN_SEP = "─" * 65


def _pct(n: int, total: int) -> str:
    return f"{n:,}  ({100 * n / total:.1f}%)" if total else "0"


def _rel(path: Path) -> str:
    """Safely display a path relative to PROJECT_ROOT, or as absolute if outside."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _entropy(series: pd.Series) -> float:
    """Shannon entropy of a categorical series (bits)."""
    counts = series.value_counts(normalize=True)
    return float(-sum(p * math.log2(p) for p in counts if p > 0))


def _flag(condition: bool, msg: str) -> str:
    return f"  ⚠  {msg}" if condition else f"  ✓  {msg}"


def _print_section(title: str) -> None:
    print(f"\n  ── {title} ──")


# ---------------------------------------------------------------------------
# Core inspector
# ---------------------------------------------------------------------------

def inspect(ds_id: str, meta: dict) -> dict[str, object]:
    """
    Inspect one dataset. Returns a summary dict.
    Prints a human-readable report to stdout.
    Never raises — returns {'status': 'missing'} if file absent.
    """
    print(f"\n{SEPARATOR}")
    print(f"  DATASET : {ds_id.upper()}")
    print(f"  MODEL   : {meta['model']}")
    print(SEPARATOR)

    csv_path: Path = meta["path"]

    # ── Existence check ──────────────────────────────────────────────
    if not csv_path.exists():
        print(f"\n  ✗  FILE NOT FOUND: {_rel(csv_path)}")
        print(f"\n  To download this dataset, run:")
        print(f"      python src/download_datasets.py")
        return {"status": "missing", "path": str(csv_path)}

    # ── Load ─────────────────────────────────────────────────────────
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        print(f"\n  ✗  LOAD ERROR: {exc}")
        return {"status": "load_error", "error": str(exc)}

    n_rows, n_cols = df.shape
    print(f"\n  File     : {_rel(csv_path)}")
    print(f"  Rows     : {n_rows:,}")
    print(f"  Columns  : {n_cols}")

    # ── Column audit ─────────────────────────────────────────────────
    _print_section("COLUMNS")
    print(f"  {'Name':<30} {'dtype':<12} {'non-null':>10} {'null':>8}")
    print(f"  {'─'*30} {'─'*12} {'─'*10} {'─'*8}")
    for col in df.columns:
        nn = df[col].notna().sum()
        nl = df[col].isna().sum()
        print(f"  {col:<30} {str(df[col].dtype):<12} {nn:>10,} {nl:>8,}")

    # ── Expected columns check ────────────────────────────────────────
    expected = meta.get("expected_cols", [])
    if expected:
        # Case-insensitive match
        actual_lower = {c.lower(): c for c in df.columns}
        missing_exp = [e for e in expected if e.lower() not in actual_lower]
        extra_cols = [c for c in df.columns if c.lower() not in {e.lower() for e in expected}]
        _print_section("EXPECTED COLUMN CHECK")
        if missing_exp:
            print(f"  ⚠  Missing expected columns : {missing_exp}")
        else:
            print(f"  ✓  All expected columns present")
        if extra_cols:
            print(f"  ℹ  Extra columns found      : {extra_cols}")

    # ── Missing values ────────────────────────────────────────────────
    _print_section("MISSING VALUES")
    missing = df.isnull().sum()
    has_missing = missing.any()
    if has_missing:
        print(f"  ⚠  Missing values detected:")
        for col, cnt in missing[missing > 0].items():
            print(f"     {col:<30} {_pct(cnt, n_rows)}")
    else:
        print(f"  ✓  No missing values")

    # ── Duplicate rows ────────────────────────────────────────────────
    _print_section("DUPLICATE ROWS")
    n_dupes = df.duplicated().sum()
    print(_flag(n_dupes > 0, f"Duplicate rows: {_pct(n_dupes, n_rows)}"))

    # ── Numeric range validation ──────────────────────────────────────
    valid_ranges: dict = meta.get("valid_ranges", {})
    if valid_ranges:
        _print_section("NUMERIC RANGE VALIDATION")
        for col, (lo, hi) in valid_ranges.items():
            # Resolve column name (case-insensitive)
            matched = actual_lower.get(col.lower(), col) if expected else col
            if matched not in df.columns:
                print(f"  ℹ  Column '{col}' not in dataframe — skipping range check")
                continue
            series = pd.to_numeric(df[matched], errors="coerce")
            out_of_range = ((series < lo) | (series > hi)).sum()
            print(_flag(out_of_range > 0,
                        f"{matched:<30} range [{lo}, {hi}]  "
                        f"out-of-range: {_pct(out_of_range, n_rows)}"))

    # ── Target variable analysis ──────────────────────────────────────
    target = meta.get("target", "")
    target_col = actual_lower.get(target.lower()) if expected else target
    if target_col and target_col in df.columns:
        _print_section(f"TARGET: {target_col}")
        t = df[target_col]
        if pd.api.types.is_numeric_dtype(t):
            print(f"  Type        : numeric (regression)")
            print(f"  Min         : {t.min():.4f}")
            print(f"  Max         : {t.max():.4f}")
            print(f"  Mean        : {t.mean():.4f}")
            print(f"  Std Dev     : {t.std():.4f}")
            print(f"  Null count  : {t.isna().sum():,}")
        else:
            vc = t.value_counts()
            n_classes = len(vc)
            entropy = _entropy(t.dropna())
            max_class_pct = vc.iloc[0] / len(t) * 100 if len(t) else 0
            imbalanced = max_class_pct > 70
            print(f"  Type        : categorical (classification)")
            print(f"  Classes     : {n_classes}")
            print(f"  Entropy     : {entropy:.3f} bits  (max={math.log2(n_classes):.3f} bits)")
            print(_flag(imbalanced, f"Class imbalance  (dominant: {vc.index[0]!r} = {max_class_pct:.1f}%)"))
            print(f"\n  {'Class':<35} {'Count':>8} {'%':>6}")
            print(f"  {'─'*35} {'─'*8} {'─'*6}")
            for cls, cnt in vc.items():
                print(f"  {str(cls):<35} {cnt:>8,} {100*cnt/len(t):>5.1f}%")
    elif target == "Yield_tonnes_per_ha":
        # Special case: yield needs to be derived
        _print_section("TARGET: Yield_tonnes_per_ha (DERIVED)")
        prod_col = actual_lower.get("production") if expected else "Production"
        area_col = actual_lower.get("area") if expected else "Area"
        if prod_col in df.columns and area_col in df.columns:
            area = pd.to_numeric(df[area_col], errors="coerce")
            prod = pd.to_numeric(df[prod_col], errors="coerce")
            zero_area = (area == 0).sum()
            null_prod = prod.isna().sum()
            yield_series = prod / area.replace(0, float("nan"))
            print(f"  Derivation  : Production / Area")
            print(f"  Zero-area rows (would cause division by zero): {zero_area:,}")
            print(f"  Null Production rows: {null_prod:,}")
            valid_yield = yield_series.dropna()
            if len(valid_yield):
                print(f"  Valid yield rows : {len(valid_yield):,}")
                print(f"  Min              : {valid_yield.min():.4f} tonnes/ha")
                print(f"  Max              : {valid_yield.max():.4f} tonnes/ha")
                print(f"  Mean             : {valid_yield.mean():.4f} tonnes/ha")
                extreme = (valid_yield > 1000).sum()
                print(_flag(extreme > 0, f"Extreme yield values (>1000 t/ha): {extreme:,}"))

    # ── Sample records ────────────────────────────────────────────────
    _print_section("SAMPLE RECORDS (first 3 rows)")
    with pd.option_context("display.max_columns", None, "display.width", 120):
        print(df.head(3).to_string(index=False))

    # ── Data leakage warning ──────────────────────────────────────────
    _print_section("DATA LEAKAGE NOTES")
    if ds_id == "crop_recommendation":
        print("  ℹ  N/P/K values are soil measures — not post-harvest. No obvious leakage.")
        print("  ℹ  Dataset is balanced by construction (100 rows per crop).")
        print("  ⚠  Uniformly balanced data may be augmented — treat accuracy metrics with care.")
    elif ds_id == "fertilizer_recommendation":
        print("  ℹ  Features represent pre-application soil state. No obvious leakage.")
        print("  ⚠  Fertilizer labels are product codes (10-26-26, DAP, Urea) not crop-stage advice.")
        print("  ⚠  Verify that label granularity is sufficient for real-world recommendations.")
    elif ds_id == "crop_yield_india":
        print("  ℹ  Yield = Production/Area — both from the same record. This is the target, not leakage.")
        print("  ⚠  'Production' column must NOT be used as a feature (it directly encodes the target).")
        print("  ⚠  Split by year (temporal) or state (geo) to avoid overfitting to historical averages.")
    elif ds_id == "irrigation":
        print("  ℹ  Soil moisture drives the irrigation decision — this is a valid causal relationship.")
        print("  ⚠  If soil moisture is measured AFTER irrigation, it would be a leakage risk.")
        print("     Verify sensor measurement timing in the dataset documentation.")

    # ── Summary dict ─────────────────────────────────────────────────
    return {
        "status": "ok",
        "rows": n_rows,
        "cols": n_cols,
        "missing_any": bool(has_missing),
        "duplicates": int(n_dupes),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FarmIQ-ML Dataset Inspector")
    parser.add_argument(
        "--dataset",
        choices=list(DATASET_META.keys()),
        help="Inspect a single dataset (default: all)",
    )
    args = parser.parse_args()

    targets = (
        {args.dataset: DATASET_META[args.dataset]}
        if args.dataset
        else DATASET_META
    )

    print("\nFarmIQ-ML — Dataset Quality Report")
    print(f"Project root: {PROJECT_ROOT}")

    summaries: dict[str, dict] = {}
    for ds_id, meta in targets.items():
        summaries[ds_id] = inspect(ds_id, meta)

    # ── Grand summary ─────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("  OVERALL SUMMARY")
    print(SEPARATOR)
    print(f"  {'Dataset':<35} {'Status':<20} {'Rows':>8} {'Cols':>5} {'Missing':>8} {'Dupes':>6}")
    print(f"  {'─'*35} {'─'*20} {'─'*8} {'─'*5} {'─'*8} {'─'*6}")
    for ds_id, s in summaries.items():
        if s.get("status") == "ok":
            flag = "⚠ missing_vals" if s["missing_any"] else "✓ clean"
            print(
                f"  {ds_id:<35} {flag:<20} {s['rows']:>8,} {s['cols']:>5} "
                f"{'Yes' if s['missing_any'] else 'No':>8} {s['duplicates']:>6,}"
            )
        else:
            print(f"  {ds_id:<35} {s['status']:<20}")

    missing_count = sum(1 for s in summaries.values() if s.get("status") == "missing")
    if missing_count:
        print(
            f"\n  {missing_count} dataset(s) missing. Run:\n"
            "      python src/download_datasets.py"
        )
    print()


if __name__ == "__main__":
    main()
