# FarmIQ-ML — Intelligent Farm Management (ML Layer)

Standalone Python ML project that powers four agricultural prediction models
for the FarmIQ platform.

---

## Models

| Model | Task | Dataset |
|-------|------|---------|
| Crop Recommendation | Multi-class classification | Kaggle — atharvaingle/crop-recommendation-dataset |
| Fertilizer Recommendation | Multi-class classification | Kaggle — gdabhishek/fertilizer-prediction |
| Crop Yield Prediction | Regression | Kaggle — abhinand05/crop-production-in-india |
| Irrigation Prediction | Binary classification | GCEKIoTCommunity (GitHub) / Mendeley |

---

## Project Structure

```
FarmIQ-ML/
├── datasets/
│   ├── raw/                           ← original, unmodified datasets
│   │   ├── crop_recommendation/
│   │   ├── fertilizer_recommendation/
│   │   ├── crop_yield_india/
│   │   └── irrigation/
│   ├── processed/                     ← preprocessed train/test splits + artefacts
│   └── README.md                      ← dataset details, schemas, licenses
├── src/
│   ├── download_datasets.py           ← Kaggle API downloader + manual instructions
│   ├── inspect_datasets.py            ← dataset quality report
│   ├── preprocess_crop_recommendation.py
│   ├── preprocess_fertilizer_recommendation.py
│   ├── preprocess_crop_yield.py
│   ├── preprocess_irrigation.py
│   └── run_all_preprocessing.py       ← runs all four pipelines in one command
├── training/                          ← model training scripts (future)
├── models/                            ← saved model files (future)
├── tests/
│   ├── conftest.py
│   └── test_preprocessing.py          ← unit tests (no real data needed)
├── requirements.txt
└── README.md                          ← this file
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Download datasets

**Automated (requires Kaggle credentials):**

```bash
# First, set up kaggle.json (one-time):
# 1. Log in at https://www.kaggle.com
# 2. Account → Settings → API → Create New Token
# 3. Save kaggle.json to: C:\Users\<YourName>\.kaggle\kaggle.json

python src/download_datasets.py
```

**Manual download:** Follow the instructions in `datasets/README.md`.  
The download script also prints step-by-step instructions when credentials are absent.

### 3. Inspect and validate datasets

```bash
# Inspect all datasets and print quality report
python src/inspect_datasets.py

# Inspect a single dataset
python src/inspect_datasets.py --dataset crop_recommendation
python src/inspect_datasets.py --dataset fertilizer_recommendation
python src/inspect_datasets.py --dataset crop_yield_india
python src/inspect_datasets.py --dataset irrigation
```

Sample output includes row/column counts, missing value report, duplicate check,
range validation, target class distribution, and data leakage warnings.

### 4. Run preprocessing

```bash
# All four pipelines in one command
python src/run_all_preprocessing.py

# Or individually
python src/preprocess_crop_recommendation.py
python src/preprocess_fertilizer_recommendation.py
python src/preprocess_crop_yield.py
python src/preprocess_irrigation.py
```

Processed artefacts (train/test CSVs, scalers, encoders) are saved to `datasets/processed/`.

### 5. Run tests

```bash
# With pytest (recommended)
python -m pytest tests/ -v

# Without pytest (standalone)
python tests/test_preprocessing.py
```

Tests use synthetic DataFrames — no real datasets required.

---

## Dataset Status

| Dataset | Status | Notes |
|---------|--------|-------|
| Crop Recommendation | Requires manual Kaggle download | See `datasets/README.md` |
| Fertilizer Recommendation | Requires manual Kaggle download | See `datasets/README.md` |
| Crop Yield India | Requires manual Kaggle download | See `datasets/README.md` |
| Irrigation | Requires GitHub/Mendeley download | See `datasets/README.md` |

---

## Kaggle API Setup (Windows)

```powershell
# 1. Install Kaggle library
pip install kaggle

# 2. Get API token
# Log in → https://www.kaggle.com → Account → Settings → API → Create New Token
# Download kaggle.json

# 3. Place credentials file
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.kaggle"
Copy-Item "$env:USERPROFILE\Downloads\kaggle.json" "$env:USERPROFILE\.kaggle\kaggle.json"

# 4. Fix permissions (required by Kaggle)
icacls "$env:USERPROFILE\.kaggle\kaggle.json" /inheritance:r /grant:r "${env:USERNAME}:R"

# 5. Run downloader
python src/download_datasets.py
```

---

## Data Integrity Rules

- Raw files in `datasets/raw/` are **never modified** by any script.
- Preprocessing scripts always read from raw and write to processed.
- All encoders and scalers are **fit on training data only** (no leakage).
- The `Production` column from the crop yield dataset is **excluded from features** — it directly encodes the target.
- Temporal split (not random) is used for crop yield to test out-of-sample generalisation.

---

## Next Steps (Before Model Training)

1. Download all four datasets (see Section 2 above).
2. Run `python src/inspect_datasets.py` — verify no unexpected issues.
3. Run `python src/run_all_preprocessing.py` — confirm all splits saved correctly.
4. Run `python -m pytest tests/ -v` — all tests should pass.
5. Review `datasets/README.md` for known limitations of each dataset.
6. Implement model training scripts in `training/` using the processed CSVs.

---

## Important: What Is Not Yet Built

- Model training scripts (`training/`)
- Saved model files (`models/`)
- FastAPI backend, frontend, authentication, or database

This repository currently covers **data acquisition, validation, and preprocessing only**.

---

## License

This project code is released under the MIT License.  
Each dataset carries its own license — see `datasets/README.md` for details.
