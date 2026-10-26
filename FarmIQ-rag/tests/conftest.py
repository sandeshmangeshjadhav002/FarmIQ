"""
pytest configuration for FarmIQ-ML tests.
Ensures the src/ directory is on sys.path so test modules can import preprocessing scripts.
"""

import sys
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
