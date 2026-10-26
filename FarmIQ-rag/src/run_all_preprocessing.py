"""
FarmIQ-ML — Run All Preprocessing Pipelines
=============================================
Convenience script that runs all four preprocessing modules in sequence.
Missing datasets are skipped with a warning; existing ones are processed.

Usage:
    python src/run_all_preprocessing.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fix Unicode output on Windows console (cp1252 can't handle ✓✗⚠▶)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import preprocess_crop_recommendation
import preprocess_fertilizer_recommendation
import preprocess_crop_yield
import preprocess_irrigation

PIPELINES = [
    ("Crop Recommendation",       preprocess_crop_recommendation.run),
    ("Fertilizer Recommendation", preprocess_fertilizer_recommendation.run),
    ("Crop Yield Prediction",     preprocess_crop_yield.run),
    ("Irrigation Prediction",     preprocess_irrigation.run),
]

SEP = "=" * 60


def main() -> None:
    print(SEP)
    print("FarmIQ-ML — Preprocessing All Datasets")
    print(SEP)

    results: list[tuple[str, str]] = []

    for name, pipeline_fn in PIPELINES:
        print(f"\n▶  {name}")
        print("─" * 50)
        try:
            summary = pipeline_fn()
            status = summary.get("status", "ok")
            if status == "missing":
                results.append((name, "SKIPPED — dataset missing"))
            else:
                results.append((name, "✓ SUCCESS"))
        except FileNotFoundError as exc:
            results.append((name, f"SKIPPED — {exc}"))
        except Exception as exc:
            results.append((name, f"✗ ERROR — {exc}"))
            import traceback
            traceback.print_exc()

    print(f"\n{SEP}")
    print("PREPROCESSING SUMMARY")
    print(SEP)
    for name, status in results:
        print(f"  {name:<35} {status}")
    print()


if __name__ == "__main__":
    main()
