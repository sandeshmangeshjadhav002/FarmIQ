# FarmIQ-ML — Datasets

This document records the datasets used across all four FarmIQ ML models,
their verified sources, licenses, column schemas, known limitations, and
preprocessing decisions.

---

## Directory Layout

```
datasets/
├── raw/
│   ├── crop_recommendation/       ← Crop_recommendation.csv
│   ├── fertilizer_recommendation/ ← Fertilizer Prediction.csv
│   ├── crop_yield_india/          ← crop_production.csv
│   └── irrigation/                ← irrigation_dataset.csv
├── processed/
│   ├── crop_recommendation/       ← train.csv, test.csv, scaler.joblib, label_encoder.joblib
│   ├── fertilizer_recommendation/ ← train.csv, test.csv, scaler.joblib, ...
│   ├── crop_yield_india/          ← train.csv, test.csv, feature_meta.json, ...
│   └── irrigation/                ← train.csv, test.csv, scaler.joblib, rule_based_baseline.json
└── README.md   ← this file
```

Raw files are **never overwritten** by preprocessing scripts.
Processed files are always regenerated from raw files.

---

## Dataset Comparison Table

| # | Dataset | Model | Source | Rows | Cols | Task | Target | Format | License |
|---|---------|-------|--------|------|------|------|--------|--------|---------|
| 1 | Crop Recommendation | Crop Recommendation | Kaggle (atharvaingle) | 2,200 | 8 | Multi-class classification | crop label (22 classes) | CSV | CC0: Public Domain |
| 2 | Fertilizer Prediction | Fertilizer Recommendation | Kaggle (gdabhishek) | ~1,000 | 9 | Multi-class classification | Fertilizer Name (7 types) | CSV | Community (CC BY-NC-SA) |
| 3 | Crop Production in India | Crop Yield Prediction | Kaggle (abhinand05) / Govt. of India | ~246,000 | 7+ | Regression | Yield = Production/Area (t/ha) | CSV | CC0: Public Domain |
| 4 | Irrigation Dataset | Irrigation Prediction | GCEKIoTCommunity (GitHub) / Mendeley | ~1,000–5,000 | 7 | Binary classification | Irrigation Y/N | CSV | Academic (MHRD-NPIU, India) |

---

## Dataset Details

### 1. Crop Recommendation

**Source page:** https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset  
**Download date:** *Fill in after download*  
**License:** CC0: Public Domain  
**Geographic scope:** India (multi-state, augmented from ICAR/IMD rainfall/climate data)

#### Columns

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| N | float | kg/ha | Nitrogen content in soil |
| P | float | kg/ha | Phosphorous content in soil |
| K | float | kg/ha | Potassium content in soil |
| temperature | float | °C | Average temperature |
| humidity | float | % | Relative humidity |
| ph | float | — | Soil pH (0–14) |
| rainfall | float | mm | Annual rainfall |
| **label** | string | — | **Target** — recommended crop name |

#### Quality Notes
- **2,200 rows × 8 columns** — 100 rows per crop (22 crops).
- No missing values documented.
- **Class balance:** Perfectly balanced by construction (100 rows per class). This is
  unusual for real agricultural data — treat high accuracy figures with scepticism.
- No duplicate rows expected.
- Covers 22 crops: rice, maize, chickpea, kidneybeans, pigeonpeas, mothbeans, mungbean,
  blackgram, lentil, pomegranate, banana, mango, grapes, watermelon, muskmelon, apple,
  orange, papaya, coconut, cotton, jute, coffee.

#### Limitations
- Balanced by construction — may overestimate real-world separability.
- No field-level metadata (district, year, season).
- pH and rainfall ranges may not fully represent extreme Indian micro-climates.

#### Preprocessing
- Duplicates removed.
- Missing values filled with column median (none expected).
- Out-of-range values clipped.
- Target label-encoded.
- Features standardised with `StandardScaler` (fit on train split only).
- Stratified 80/20 split.

---

### 2. Fertilizer Recommendation (Fertilizer Prediction)

**Source page:** https://www.kaggle.com/datasets/gdabhishek/fertilizer-prediction  
**Download date:** *Fill in after download*  
**License:** Kaggle Community default (CC BY-NC-SA 4.0)  
**Geographic scope:** India

#### Columns

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| Temparature | float | °C | Air temperature (note: original dataset typo retained) |
| Humidity | float | % | Relative humidity |
| Moisture | float | % | Soil moisture |
| Soil Type | string | — | Soil category (Sandy, Loamy, Black, Red, Clayey, …) |
| Crop Type | string | — | Crop being cultivated (Wheat, Paddy, Maize, …) |
| Nitrogen | float | kg/ha | Soil nitrogen |
| Potassium | float | kg/ha | Soil potassium |
| Phosphorous | float | kg/ha | Soil phosphorous |
| **Fertilizer Name** | string | — | **Target** — fertilizer to apply |

#### Fertilizer Labels and Credibility

| Label | Type | Agricultural meaning |
|-------|------|---------------------|
| Urea | Nitrogenous | 46% N — most common N fertilizer in India |
| DAP | Complex | Di-Ammonium Phosphate — 18%N + 46%P₂O₅ |
| 14-35-14 | Complex | N:P:K = 14:35:14 |
| 28-28 | Complex | N:P = 28:28 |
| 17-17-17 | Complex NPK | Balanced N:P:K = 17:17:17 |
| 20-20 | Complex | N:P = 20:20 |
| 10-26-26 | Complex | N:P:K = 10:26:26 |

All seven labels correspond to real, commercially available fertilizer grades used in
Indian agriculture. Labels are agriculturally credible.

#### Quality Notes
- Moderate dataset (~1,000 rows) — verify after download.
- Column name has a known typo: "Temparature" (not "Temperature") — retained for fidelity.
- Minor class imbalance possible — check with `src/inspect_datasets.py`.

#### Limitations
- Does not include soil pH, which affects nutrient availability.
- Fertilizer recommendations represent a single product, not a full nutrient management plan.
- "Soil Type" categories may not match all Indian soil classification systems.

#### Preprocessing
- Column names normalised (whitespace, alternative spellings handled).
- `OrdinalEncoder` for Soil Type and Crop Type (fit on train split only).
- `LabelEncoder` for target.
- `StandardScaler` for numeric columns (fit on train only).
- Stratified 80/20 split.

---

### 3. Crop Production in India

**Source page:** https://www.kaggle.com/datasets/abhinand05/crop-production-in-india  
**Underlying source:** Government of India agriculture statistics (ICRISAT / NHB)  
**Download date:** *Fill in after download*  
**License:** CC0: Public Domain  
**Geographic scope:** India (state + district level, 1997–2020 approx.)

#### Columns

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| State_Name | string | — | Indian state |
| District_Name | string | — | District within state |
| Crop_Year | int | year | Year of cultivation |
| Season | string | — | Kharif, Rabi, Whole Year, Summer, Winter, Autumn |
| Crop | string | — | Crop name |
| Area | float | hectares | Cultivated area |
| Production | float | metric tonnes | Total production |
| **Yield_tonnes_per_ha** | float | t/ha | **Target** — *derived:* Production ÷ Area |

Optional columns (may be present in some versions):
Annual_Rainfall (mm), Fertilizer (kg), Pesticide (kg)

#### Critical Notes on Leakage
- **`Production` must NOT be used as a feature.**  
  It directly encodes the target: Yield = Production / Area.  
  Including it would constitute data leakage.
- The preprocessing script explicitly excludes `Production` from features.

#### Yield Derivation
```
Yield_tonnes_per_ha = Production (metric tonnes) / Area (hectares)
```
- Rows with zero area are dropped (division by zero).
- Rows where Production is null are dropped.
- Extreme outliers above the 99.5th percentile are clipped.
- Log-transform (`log1p`) applied to target — reverse with `expm1()`.

#### Quality Notes
- ~246,000 rows (varies by version — verify after download).
- Known missing values in Production (~3,000 rows).
- Some crops have very small area records leading to unrealistic yield values.
- Year coverage typically 1997–2020.

#### Temporal Split
Train: Crop_Year ≤ 2013  
Test : Crop_Year > 2013  
This is preferred over random split to evaluate out-of-sample generalisation.

#### Limitations
- No weather data in base version (only Annual_Rainfall in extended versions).
- State/district-level aggregates hide field-level variation.
- Crop name spellings are inconsistent (e.g. "Rice" vs "Paddy") — standardise before merging.

---

### 4. Irrigation Prediction

**Primary source:** https://github.com/GCEKIoTCommunity/Irrigation-Dataset  
**Institution:** Dept. of CSE, Govt. College of Engineering Kalahandi +
Parala Maharaja Engineering College, Odisha, India  
**Funding:** MHRD-NPIU Collaborative Research Scheme, Government of India  
**Alternate source:** https://data.mendeley.com/datasets/fpdwmm7nrb/1  
  (Soil Moisture, Air Temperature, Humidity, Motor on/off — Manipal University Jaipur)  
**Download date:** *Fill in after download*  
**License:** Academic / Research use  

#### Columns — Primary (GCEKIoT)

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| CropType | string | — | Paddy (1), Ground Nuts (2) |
| CropDays | int | days | Days since planting |
| SoilMoisture | float | % | Soil moisture content |
| SoilTemperature | float | °C | Soil temperature |
| Temperature | float | °C | Air temperature |
| Humidity | float | % | Relative humidity |
| **Irrigation** | binary | Y/N→1/0 | **Target** — irrigate or not |

#### Columns — Alternate (Mendeley)

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| Soil_Moisture | float | % | Soil moisture |
| Temperature | float | °C | Air temperature |
| Humidity | float | % | Humidity |
| Motor_Status | binary | 1/0 | **Target** — motor (pump) on/off |

#### Quality Notes
- Binary classification: balanced or mildly imbalanced depending on sensor conditions.
- Sensor-collected data — verify measurement timing (moisture before or after irrigation?).
- Small dataset — consider cross-validation over a single train/test split.
- GCEKIoT dataset: only 2 crop types (Paddy, Ground Nuts) — generalisation to other crops limited.

#### Limitations
- No growth stage (vegetative, flowering, grain fill) unless derived from CropDays.
- No soil type, soil texture, or evapotranspiration data.
- Results may not generalise beyond Odisha's agro-climatic zone.
- Sensor data may have measurement artefacts.

#### Rule-Based Baseline

When supervised data is unavailable or unreliable, use this documented baseline:

```
IF SoilMoisture < 30% THEN irrigate = 1  ELSE irrigate = 0
```

Rationale: Soil moisture below ~30% of field capacity is a widely used irrigation
trigger in Indian Kharif/Rabi crops (ICAR guidelines). Any trained ML model must
beat this baseline to justify the added complexity.

The baseline is saved to `datasets/processed/irrigation/rule_based_baseline.json`.

---

## Preprocessing Steps Summary

| Step | Crop Rec | Fertilizer | Crop Yield | Irrigation |
|------|----------|------------|------------|------------|
| Remove duplicates | ✓ | ✓ | ✓ | ✓ |
| Fill missing (median/mode) | ✓ | ✓ | ✓ | ✓ |
| Clip out-of-range values | ✓ | ✓ | ✓ | ✓ |
| Encode categoricals | LabelEncoder | OrdinalEncoder | OrdinalEncoder | LabelEncoder |
| Scale numerics | StandardScaler | StandardScaler | StandardScaler | StandardScaler |
| Train/test split | Stratified 80/20 | Stratified 80/20 | Temporal (≤2013 / >2013) | Stratified 80/20 |
| Log-transform target | — | — | log1p(Yield) | — |
| Fit on train only | ✓ | ✓ | ✓ | ✓ |

---

## How to Download Datasets

### Automated (requires Kaggle API credentials)

```bash
# Step 1: Get your API token
# Log in at https://www.kaggle.com → Account → Settings → API → Create New Token
# Save kaggle.json to:  C:\Users\<YourName>\.kaggle\kaggle.json

# Step 2: Run the download script
python src/download_datasets.py
```

### Manual Download Instructions

#### Crop Recommendation
1. Go to: https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset
2. Click Download → Extract ZIP
3. Copy `Crop_recommendation.csv` → `datasets/raw/crop_recommendation/`

#### Fertilizer Recommendation
1. Go to: https://www.kaggle.com/datasets/gdabhishek/fertilizer-prediction
2. Click Download → Extract ZIP
3. Copy `Fertilizer Prediction.csv` → `datasets/raw/fertilizer_recommendation/`

#### Crop Yield (India)
1. Go to: https://www.kaggle.com/datasets/abhinand05/crop-production-in-india
2. Click Download → Extract ZIP
3. Copy the main CSV → `datasets/raw/crop_yield_india/crop_production.csv`

#### Irrigation
**Option A — GCEKIoT GitHub:**
1. Go to: https://github.com/GCEKIoTCommunity/Irrigation-Dataset
2. Download the CSV file from the repository
3. Save as: `datasets/raw/irrigation/irrigation_dataset.csv`

**Option B — Mendeley (free account needed):**
1. Go to: https://data.mendeley.com/datasets/fpdwmm7nrb/1
2. Click Download All
3. Save CSV as: `datasets/raw/irrigation/irrigation_dataset.csv`

---

## Citation / Attribution

If you use these datasets in research or publications:

- **Crop Recommendation** (Kaggle, Atharva Ingle): Cite original Kaggle dataset page.
- **Fertilizer Prediction** (Kaggle, gdabhishek): Cite Kaggle dataset page.
- **Crop Production India** (Kaggle, abhinand05): Data sourced from Government of India open data portals; cite accordingly.
- **Irrigation Dataset** (GCEKIoTCommunity): Acknowledge MHRD-NPIU CRS scheme, GCE Kalahandi & PMEC Berhampur, Odisha, India.
- **Irrigation Alt** (Mendeley, Kaur et al., 2023): DOI: 10.17632/fpdwmm7nrb.1

---

*Last updated: October 2026*
