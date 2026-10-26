"""
FarmIQ-ML — Dataset Downloader
================================
Attempts to download all four datasets using the Kaggle API.
Falls back to clear manual instructions when credentials are absent.

Usage:
    python src/download_datasets.py

Requirements:
    pip install kaggle

Kaggle credentials setup (one-time):
    1. Log in at https://www.kaggle.com
    2. Go to Account → Settings → API → Create New Token
    3. Save the downloaded kaggle.json to:
       Windows : C:\\Users\\<YourName>\\.kaggle\\kaggle.json
       Linux/Mac: ~/.kaggle/kaggle.json
    4. On Windows the file must NOT be readable by other users (Kaggle checks this).
       If you get a permissions error run:
           icacls "%USERPROFILE%\\.kaggle\\kaggle.json" /inheritance:r /grant:r "%USERNAME%:R"
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠→)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "datasets" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Dataset registry
# ---------------------------------------------------------------------------
DATASETS = [
    {
        "id": "crop_recommendation",
        "kaggle_ref": "atharvaingle/crop-recommendation-dataset",
        "expected_file": "Crop_recommendation.csv",
        "target_dir": RAW_DIR / "crop_recommendation",
        "model": "Crop Recommendation",
        "license": "CC0: Public Domain",
        "source_url": "https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset",
        "manual_steps": (
            "1. Open https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset\n"
            "2. Click the Download button (top-right).\n"
            "3. Extract the ZIP and copy Crop_recommendation.csv to:\n"
            "   datasets/raw/crop_recommendation/"
        ),
    },
    {
        "id": "fertilizer_recommendation",
        "kaggle_ref": "gdabhishek/fertilizer-prediction",
        "expected_file": "Fertilizer Prediction.csv",
        "target_dir": RAW_DIR / "fertilizer_recommendation",
        "model": "Fertilizer Recommendation",
        "license": "CC BY-NC-SA 4.0 (Kaggle default community)",
        "source_url": "https://www.kaggle.com/datasets/gdabhishek/fertilizer-prediction",
        "manual_steps": (
            "1. Open https://www.kaggle.com/datasets/gdabhishek/fertilizer-prediction\n"
            "2. Click the Download button.\n"
            "3. Extract and copy 'Fertilizer Prediction.csv' to:\n"
            "   datasets/raw/fertilizer_recommendation/"
        ),
    },
    {
        "id": "crop_yield_india",
        "kaggle_ref": "abhinand05/crop-production-in-india",
        "expected_file": "crop_production.csv",
        "target_dir": RAW_DIR / "crop_yield_india",
        "model": "Crop Yield Prediction",
        "license": "CC0: Public Domain (Government of India open data)",
        "source_url": "https://www.kaggle.com/datasets/abhinand05/crop-production-in-india",
        "manual_steps": (
            "1. Open https://www.kaggle.com/datasets/abhinand05/crop-production-in-india\n"
            "2. Click Download.\n"
            "3. Extract and copy crop_production.csv to:\n"
            "   datasets/raw/crop_yield_india/\n"
            "   (The file may also be named 'crop_production.csv' or similar — check after extracting.)"
        ),
    },
    {
        "id": "irrigation",
        "kaggle_ref": None,  # Not on Kaggle — GitHub / Mendeley sources
        "expected_file": "irrigation_dataset.csv",
        "target_dir": RAW_DIR / "irrigation",
        "model": "Irrigation Prediction",
        "license": "Academic / Research use (MHRD-NPIU, Government of India)",
        "source_url": "https://github.com/GCEKIoTCommunity/Irrigation-Dataset",
        "manual_steps": (
            "Primary source (recommended):\n"
            "  1. Open https://github.com/GCEKIoTCommunity/Irrigation-Dataset\n"
            "  2. Download the CSV file(s) from the repository.\n"
            "  3. Rename to 'irrigation_dataset.csv' and place in:\n"
            "     datasets/raw/irrigation/\n\n"
            "Alternative source (Mendeley, requires free account):\n"
            "  1. Open https://data.mendeley.com/datasets/fpdwmm7nrb/1\n"
            "     (Soil Moisture, Air Temperature, Humidity, Motor on/off)\n"
            "  2. Click Download All and save CSV to:\n"
            "     datasets/raw/irrigation/\n"
            "  3. Rename to 'irrigation_dataset.csv'\n\n"
            "Note: The GCEKIoT dataset has 7 columns including Irrigation(Y/N).\n"
            "      The Mendeley dataset has Soil_Moisture, Temperature, Humidity, Motor_Status.\n"
            "      Either is usable for binary irrigation classification."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kaggle_available() -> bool:
    """Return True only when kaggle.json is present and readable."""
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.exists():
        return False
    try:
        with open(cred) as f:
            data = json.load(f)
        return bool(data.get("username")) and bool(data.get("key"))
    except Exception:
        return False


def _download_kaggle(ref: str, dest: Path) -> bool:
    """Download a Kaggle dataset into dest. Returns True on success."""
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable, "-m", "kaggle",
            "datasets", "download",
            "--dataset", ref,
            "--path", str(dest),
            "--unzip",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [KAGGLE ERROR] {result.stderr.strip()}")
        return False
    return True


def _find_csv(directory: Path) -> list[Path]:
    """Recursively find CSV files in directory."""
    return list(directory.rglob("*.csv"))


def _rename_if_needed(directory: Path, expected: str) -> None:
    """If only one CSV exists and it doesn't match the expected name, rename it."""
    csvs = _find_csv(directory)
    target = directory / expected
    if target.exists():
        return
    if len(csvs) == 1:
        csvs[0].rename(target)
        print(f"  Renamed '{csvs[0].name}' → '{expected}'")
    elif len(csvs) > 1:
        print(f"  Multiple CSVs found: {[c.name for c in csvs]}")
        print(f"  Please manually rename the correct file to '{expected}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("FarmIQ-ML — Dataset Downloader")
    print("=" * 60)

    kaggle_ok = _kaggle_available()
    if kaggle_ok:
        print("✓ Kaggle credentials found — will attempt automated downloads.\n")
    else:
        print(
            "✗ Kaggle credentials NOT found.\n"
            "  Automated download is skipped for Kaggle datasets.\n"
            "  Manual download instructions will be printed below.\n"
        )

    results: list[dict] = []

    for ds in DATASETS:
        print(f"\n{'─' * 50}")
        print(f"Dataset : {ds['id']}")
        print(f"Model   : {ds['model']}")
        print(f"Source  : {ds['source_url']}")
        print(f"License : {ds['license']}")

        target_dir: Path = ds["target_dir"]
        target_dir.mkdir(parents=True, exist_ok=True)
        expected_path = target_dir / ds["expected_file"]

        # Already downloaded?
        if expected_path.exists():
            print(f"  ✓ Already present: {expected_path.relative_to(PROJECT_ROOT)}")
            results.append({"id": ds["id"], "status": "already_present"})
            continue

        # Try Kaggle automated download
        if ds["kaggle_ref"] and kaggle_ok:
            print(f"  → Downloading via Kaggle API: {ds['kaggle_ref']}")
            ok = _download_kaggle(ds["kaggle_ref"], target_dir)
            if ok:
                _rename_if_needed(target_dir, ds["expected_file"])
                if expected_path.exists():
                    size_kb = expected_path.stat().st_size // 1024
                    print(f"  ✓ Downloaded ({size_kb} KB): "
                          f"{expected_path.relative_to(PROJECT_ROOT)}")
                    results.append({"id": ds["id"], "status": "downloaded"})
                else:
                    print(f"  ⚠ Downloaded but expected file not found. "
                          f"Check {target_dir.relative_to(PROJECT_ROOT)}")
                    results.append({"id": ds["id"], "status": "downloaded_wrong_name"})
                continue
            else:
                print("  ✗ Kaggle download failed.")

        # Manual instructions
        print(f"\n  ── MANUAL DOWNLOAD INSTRUCTIONS ──")
        for line in ds["manual_steps"].splitlines():
            print(f"  {line}")
        results.append({"id": ds["id"], "status": "manual_required"})

    # Summary
    print(f"\n{'=' * 60}")
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    for r in results:
        icon = "✓" if r["status"] in ("downloaded", "already_present") else "⚠"
        print(f"  {icon}  {r['id']:35s}  {r['status']}")

    manual_count = sum(1 for r in results if r["status"] == "manual_required")
    if manual_count:
        print(
            f"\n  {manual_count} dataset(s) require manual download.\n"
            "  After placing CSV files in the correct directories,\n"
            "  re-run this script to verify, then run:\n"
            "      python src/inspect_datasets.py"
        )
    else:
        print("\n  All datasets present. Run: python src/inspect_datasets.py")


if __name__ == "__main__":
    main()
