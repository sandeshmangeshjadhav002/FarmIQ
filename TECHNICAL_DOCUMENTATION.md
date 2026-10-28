# FarmIQ — Technical Documentation

> **An Intelligent Smart Agriculture MLOps Platform**
> How the project is built, what technology it uses, and why each decision was made.

|                         |                                                                      |
| ----------------------- | -------------------------------------------------------------------- |
| **Document date**       | 2026-10-28                                                           |
| **Evaluation baseline** | `backend/ml/reports/evaluation_report.json` (2026-10-26)             |
| **Runtime verified**    | Python 3.14.5 · scikit-learn 1.9.0 · Vite 8.3.4 · Capacitor 8.5.3    |
| **Backend port**        | `8001` (8000 is frequently occupied on Windows)                      |
| **Frontend dev port**   | `5173`                                                               |
| **Deployment target**   | Render — `farmiq-api` (Docker) + `farmiq-web` (Static Site); see §19 |
| **Backend tests**       | 198 passing, 0 warnings                                              |
| **Frontend tests**      | 43 passing (Vitest + jsdom, 5 files)                                 |

---

## Table of contents

1. [What FarmIQ is](#1-what-farmiq-is)
2. [Repository layout](#2-repository-layout)
3. [Technology stack](#3-technology-stack)
4. [Architecture](#4-architecture)
5. [ML subsystem](#5-ml-subsystem)
6. [Database](#6-database)
7. [Weather integration](#7-weather-integration)
8. [IoT integration and sensor simulator](#8-iot-integration-and-sensor-simulator)
9. [Government schemes](#9-government-schemes)
10. [Pre-existing subsystems (RAG assistant and voice)](#10-pre-existing-subsystems-rag-assistant-and-voice)
11. [Frontend architecture](#11-frontend-architecture)
12. [Android packaging (Capacitor)](#12-android-packaging-capacitor)
13. [Environment variables](#13-environment-variables)
14. [Build and run](#14-build-and-run)
15. [Testing](#15-testing)
16. [Engineering rules applied](#16-engineering-rules-applied)
17. [Known limitations](#17-known-limitations)
18. [Deliberately not implemented](#18-deliberately-not-implemented)
19. [Production deployment](#19-production-deployment)

---

## 1. What FarmIQ is

FarmIQ is a mobile-first agricultural advisory platform. A React web app is wrapped
with Capacitor to ship as an Android application; a FastAPI backend owns all data
access, authentication and machine-learning inference; Supabase provides the
Postgres database and the identity provider.

The platform is deliberately split into **17 user-facing modules** grouped as
Manage / Plan / Monitor / Learn / Administration, all reached through a
state-driven navigation shell rather than a client-side router.

The distinguishing engineering constraint of this project is that **nothing is
fabricated**. Predictions come from real trained scikit-learn models, evaluation
metrics come from real held-out test splits, weather data comes from a live
provider, and scheme information comes from official government sources. Where a
component cannot be built reliably, the system says so — HTTP 501, an explicit
"not evaluated" card, or a `needs_verification` badge — instead of inventing a
plausible-looking value.

---

## 2. Repository layout

```
FarmIQ-copy/
├── src/                       # React frontend (JavaScript / JSX — no TypeScript source)
│   ├── components/
│   │   ├── common/            # Button, Icon, Logo, TextInput, MicrophoneButton
│   │   ├── layout/            # DesktopNavigation, BottomNavigation, ScreenShell, …
│   │   └── modules/           # One component per product module
│   ├── config/api.js          # Single source of truth for the backend base URL
│   ├── constants/             # languages.js (11 locales), icons.jsx (inline SVG set)
│   ├── data/modules.js        # Master module catalog + all demo/seed content
│   ├── hooks/                 # useApi.js, useSpeech.js
│   ├── lib/                   # apiClient.js (fetch wrapper), languageUtils.js
│   ├── pages/                 # LoginScreen, RegisterScreen, HomeScreen, ChatScreen, …
│   ├── App.jsx                # Root component — the navigation state machine
│   └── main.jsx               # React entry point
│
├── backend/                   # FastAPI application (Python)
│   ├── app/
│   │   ├── main.py            # App factory, CORS, lifespan, router registration
│   │   ├── config.py          # pydantic-settings; all env vars live here
│   │   ├── supabase_client.py # Privileged service-role client (FastAPI dependency)
│   │   ├── auth.py            # Access-token verification → current_user dependency
│   │   ├── db.py              # Data-access layer; every query is owner-scoped
│   │   ├── schemas.py         # Pydantic v2 request/response models
│   │   ├── errors.py          # Centralised exception types + handlers
│   │   ├── logging_conf.py    # Structured logging setup
│   │   ├── weather.py         # Open-Meteo client + auto-fill report builder
│   │   ├── simulator.py       # Sensor simulator (DEMO DATA generator)
│   │   ├── rag_service.py     # Bridge to the standalone FarmIQ-RAG project
│   │   ├── voice_engine.py    # Speech orchestration
│   │   ├── tts_service.py     # Server-side text-to-speech (edge-tts)
│   │   ├── data/
│   │   │   └── government_schemes.json    # Verified scheme reference data
│   │   └── routers/           # 14 routers — see §4.1
│   ├── ml/
│   │   ├── adapter.py         # Wraps preprocessing artefacts + trained models
│   │   ├── validation.py      # Supported ranges, training ranges, warnings
│   │   ├── evaluate.py        # Evaluation harness → ml/reports/
│   │   ├── train_models.py    # Optional trainer (writes real model.joblib files)
│   │   ├── defaults.py        # Domain definitions / defaults
│   │   └── reports/           # evaluation_report.json + .md (committed)
│   ├── supabase/migrations/   # 0001_init.sql, 0002_sensor_demo_and_npk.sql
│   ├── tests/                 # pytest suite (16 modules)
│   └── requirements.txt
│
├── android/                   # Capacitor Android project (Gradle)
├── FarmIQ-rag/                # Separate sub-project: datasets, models, RAG code
│   ├── datasets/raw/          # Kaggle CSV/XLSX snapshots (as downloaded)
│   ├── datasets/processed/    # train.csv / test.csv + scalers, encoders, label maps
│   ├── models/                # <domain>/model.joblib  (gitignored)
│   ├── src/preprocess_*.py    # The preprocessing scripts that define the splits
│   └── FarmIQ-RAG/            # Standalone RAG package (own venv, own .env)
│
├── capacitor.config.ts
├── package.json               # npm scripts incl. cap:sync / cap:open / android
├── readme.md                  # Product overview
└── .env.example               # VITE_API_BASE_URL template
```

**Why `FarmIQ-rag/` is a sibling directory and not a backend package.**
The datasets and the trained models are produced by standalone preprocessing
scripts that long predate the backend. Keeping them outside `backend/` means the
backend never mutates training data; it only reads artefacts. `config.py` resolves
all ML paths relative to its own file so the backend works from any working
directory.

---

## 3. Technology stack

### 3.1 Frontend

| Technology               | Version                  | Role                                                                     |
| ------------------------ | ------------------------ | ------------------------------------------------------------------------ |
| **React**                | `^19.0.0`                | UI framework                                                             |
| **Vite**                 | `^8.0.5` (running 8.3.4) | Dev server + bundler (Rolldown-based)                                    |
| **Tailwind CSS**         | `^4.0.0`                 | Utility-first styling via `@tailwindcss/vite`                            |
| **@vitejs/plugin-react** | `^6.0.0`                 | JSX transform + Fast Refresh                                             |
| **oxfmt**                | `^0.2.0`                 | Formatter (`npm run format`)                                             |
| **TypeScript**           | `^5.7.0`                 | **Dev-only** — types for editor IntelliSense; all source is `.jsx`/`.js` |

The application source is plain JavaScript. TypeScript is present only for
`@types/react` / `@types/node` tooling support.

### 3.2 Backend

| Technology                    | Version   | Role                                                |
| ----------------------------- | --------- | --------------------------------------------------- |
| **Python**                    | 3.14      | Runtime                                             |
| **FastAPI**                   | `>=0.115` | ASGI web framework                                  |
| **uvicorn[standard]**         | `>=0.30`  | ASGI server                                         |
| **Pydantic**                  | `>=2.7`   | Request/response validation                         |
| **pydantic-settings**         | `>=2.3`   | Env-driven configuration with `lru_cache` singleton |
| **supabase**                  | `>=2.7`   | Server-side Supabase client                         |
| **python-jose[cryptography]** | `>=3.3`   | JWT verification                                    |
| **httpx**                     | `>=0.27`  | Outbound HTTP (weather API)                         |
| **python-multipart**          | `>=0.0.9` | Audio upload parsing                                |
| **edge-tts**                  | `>=6.1`   | Free Microsoft neural voices for TTS                |
| **python-dotenv**             | `>=1.0`   | `.env` loading                                      |
| **email-validator**           | `>=2.0`   | Pydantic `EmailStr` support                         |

### 3.3 Machine learning

| Technology       | Version                 | Role                                   |
| ---------------- | ----------------------- | -------------------------------------- |
| **scikit-learn** | `>=1.5` (running 1.9.0) | Model training + inference             |
| **numpy**        | `>=1.26`                | Array maths                            |
| **joblib**       | `>=1.4`                 | Artefact + model persistence           |
| **pandas**       | `>=2.2`                 | Training script only (optional import) |

Models in use: `RandomForestClassifier` for crop (22 classes), fertilizer
(13 classes) and irrigation (2 classes); `RandomForestRegressor` for yield
(log-transformed target, inverted with `expm1`).

### 3.4 Database and authentication

| Technology             | Role                                                                           |
| ---------------------- | ------------------------------------------------------------------------------ |
| **Supabase Postgres**  | Primary datastore                                                              |
| **Supabase Auth**      | Identity provider — user creation and password verification happen server-side |
| **Row Level Security** | Defence-in-depth backstop on every table                                       |
| **Service-role key**   | Server-side only; bypasses RLS, so `db.py` filters by `owner_id` explicitly    |

### 3.5 Mobile

| Technology                                  | Version                                                      | Role                                      |
| ------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------- |
| **Capacitor core / cli / android**          | `^8.5.3`                                                     | Native Android shell around the web build |
| **@capacitor/app**                          | `^8.1.2`                                                     | App lifecycle events                      |
| **@capacitor-community/speech-recognition** | `^7.0.1`                                                     | On-device speech-to-text                  |
| **@capacitor-community/text-to-speech**     | `^8.0.2`                                                     | On-device text-to-speech                  |
| **Gradle**                                  | 8.14.3                                                       | Android build system                      |
| **Android SDK**                             | min 24 · compile 36 · target 36                              | `android/variables.gradle`                |
| **AndroidX**                                | activity 1.11.0, core 1.17.0, appcompat 1.7.1, webkit 1.14.0 | Native dependencies                       |
| **JDK**                                     | Android Studio bundled JBR                                   | Gradle toolchain                          |

### 3.6 Tooling

| Tool                                             | Purpose                                                                       |
| ------------------------------------------------ | ----------------------------------------------------------------------------- |
| **pytest** `>=8.3` + **pytest-asyncio** `>=0.23` | Backend test suite                                                            |
| **Git**                                          | Version control (local milestone commits; no automatic pushes)                |
| **Vitest-compatible**                            | _Not used_ — frontend correctness is currently verified by build + manual E2E |

### 3.7 External services

| Service                                         | Auth                                       | Used for                                              |
| ----------------------------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| **Open-Meteo Forecast API**                     | None (key-less)                            | Current observation + daily rainfall history/forecast |
| **Open-Meteo Geocoding API**                    | None (key-less)                            | Place name → coordinates                              |
| **Groq (OpenAI-compatible)**                    | `STT_API_KEY`                              | Server-side Whisper transcription (optional)          |
| **Microsoft Edge neural voices** via `edge-tts` | None                                       | Marathi/Hindi/English TTS (optional)                  |
| **Supabase**                                    | Keys                                       | Postgres + Auth                                       |
| **RAG LLM**                                     | Configured in `FarmIQ-rag/FarmIQ-RAG/.env` | Chat assistant (pre-existing subsystem)               |

No weather API key exists anywhere in the system, by design — that removes a whole
class of secret-leakage risk from the auto-fill feature.

---

## 4. Architecture

### 4.1 Request flow

```
┌──────────────────────────┐
│ React 19 (browser/WebView)│
│  pages/ → components/     │
│  apiClient.js (fetch)     │
└────────────┬─────────────┘
             │  Authorization: Bearer <supabase access_token>
             ▼
┌──────────────────────────┐
│ FastAPI (uvicorn :8001)   │
│  routers/ → schemas.py    │
│  auth.py → db.py          │
└───┬───────────┬──────────┘
    │           │
    │           ├──► ml/adapter.py ──► FarmIQ-rag/models/*/model.joblib
    │           │                     FarmIQ-rag/datasets/processed/*
    │           │
    │           ├──► weather.py ─────► api.open-meteo.com  (key-less)
    │           │
    │           └──► rag_service.py ─► FarmIQ-rag/FarmIQ-RAG (separate process pkg)
    │
    ▼
┌──────────────────────────┐
│ Supabase (Postgres + Auth)│
│  service-role client      │
│  + owner_id filtering     │
│  + RLS policies           │
└──────────────────────────┘
```

**14 routers** registered in `app/main.py`:

| Router        | Prefix                 | Purpose                                        |
| ------------- | ---------------------- | ---------------------------------------------- |
| `health`      | `/`, `/api/health`     | Liveness, DB connectivity, ML model status     |
| `auth`        | `/api/auth`            | Register, login (mobile + password)            |
| `users`       | `/api/users`           | Profile read/update                            |
| `farms`       | `/api/farms`           | Farm CRUD                                      |
| `devices`     | `/api/devices`         | Pairing, listing, token issuing                |
| `sensors`     | `/api/sensor-readings` | Ingestion (user **or** device token) + history |
| `predictions` | `/api/predictions`     | 4 ML domains, schema endpoint, history         |
| `dashboard`   | `/api/dashboard`       | Aggregated counts                              |
| `chat`        | `/api/chat`            | RAG assistant                                  |
| `voice`       | `/api/voice`           | Transcribe, speak, voice chat                  |
| `weather`     | `/api/weather`         | Current conditions + auto-fill report          |
| `simulator`   | `/api/simulator`       | Sensor simulator config + demo readings        |
| `schemes`     | `/api/schemes`         | Government scheme reference data               |
| `mlops`       | `/api/mlops`           | Evaluation report                              |

### 4.2 Authentication

The frontend's original contract was preserved: it posts **`mobile` + `password`**,
not email. The backend:

1. Maps `mobile → email` through the `profiles` table.
2. Calls Supabase Auth with the **service-role key** to create or verify the user.
3. Returns the user object **plus** `access_token` and `refresh_token`.
4. The frontend stores the access token and sends `Authorization: Bearer …` on
   protected requests.

This kept every existing frontend call site working while introducing real,
server-verified sessions.

### 4.3 Authorisation and data isolation

A single privileged Supabase client is constructed with the **service-role key**.
That client bypasses Row Level Security, so isolation is enforced in two layers:

1. **Application layer (primary).** Every function in `db.py` takes `owner_id`
   and applies it as an explicit filter. There is no code path that queries a
   user-owned table without an owner filter.
2. **Database layer (backstop).** RLS policies in the migrations constrain the
   same rows for any client that is _not_ using the service-role key.

The service-role key is never referenced by frontend code and never leaves the
backend process. Device ingestion has a third path for ESP32 hardware: a random
`secrets.token_urlsafe(32)` device token plus an `X-Device-Id` header, validated
against the paired device record.

### 4.4 Error model

`app/errors.py` defines a small hierarchy so every failure maps to one predictable
JSON shape — `{ "detail": "…" }`, which is what the existing frontend already
reads.

| Exception                 | HTTP         | Used when                                                             |
| ------------------------- | ------------ | --------------------------------------------------------------------- |
| `AppError`                | configurable | Base class; carries an optional extra `hint`                          |
| `NotFoundError`           | 404          | Row absent, or owned by another user                                  |
| `ConflictError`           | 409          | Duplicate registration                                                |
| `AuthorizationError`      | 401/403      | Token invalid, or resource not owned                                  |
| `ModelNotAvailableError`  | **501**      | No trained model file for the requested domain                        |
| `InputValidationError`    | **422**      | Semantic validation failed — carries `errors`, `warnings`, `advisory` |
| `WeatherUnavailableError` | **503**      | Provider unreachable/unreadable, or feature disabled                  |

The **501** choice is deliberate: a missing model is not a server fault and must
never be masked by a fabricated prediction.

---

## 5. ML subsystem

### 5.1 Datasets

Four domains, all sourced from public Kaggle snapshots and stored under
`FarmIQ-rag/datasets/`:

| Domain                      | Raw source                                                    | Rows (train / test) |
| --------------------------- | ------------------------------------------------------------- | ------------------- |
| `crop_recommendation`       | `Crop_recommendation.csv`                                     | 1760 / 440          |
| `fertilizer_recommendation` | `Fertilizer Prediction.csv`                                   | 109 / 28            |
| `crop_yield_india`          | `crop_production.csv`                                         | 13302 / 6177        |
| `irrigation`                | `irrigation_dataset.csv` + `Project_datasheet_2019-2020.xlsx` | 120 / 30            |

### 5.2 Preprocessing artefacts

`datasets/processed/<domain>/` holds **both** the split CSVs and the fitted
transformers:

```
crop_recommendation/   label_map.json, train.csv, test.csv              (+ scaler/encoder)
fertilizer_recommendation/ fertilizer_map.json, train.csv, test.csv
crop_yield_india/      feature_meta.json, train.csv, test.csv
irrigation/            feature_meta.json, rule_based_baseline.json, train.csv, test.csv
```

The `feature_meta.json` files define the **exact feature order** the models expect.
The adapter honours that order rather than assuming column order — this is the
single most common source of silent ML-serving bugs (skew between training and
serving).

A subtle but important detail: `processed/*.csv` contain **scaled** values, so
dataset averages for default-filling must be read from `datasets/raw/` instead.
`config.py` exposes a separate `farmiq_ml_raw_path` for exactly this reason.

### 5.3 The adapter

`ml/adapter.py` is the single boundary between the API and the ML artefacts. For
each domain it loads the domain's scaler/encoder/label map plus (if present) the
trained model, then:

1. Builds a feature vector in the exact order from `feature_meta.json`.
2. Applies the same scaling/encoding the training pipeline used.
3. Calls `predict` / `predict_proba`.
4. Inverse-transforms the result into a human-readable label.
5. Returns a consistent envelope: `prediction`, `source`, `details`.

Because both the preprocessing artefacts and the models are loaded through one
adapter, retraining is a matter of replacing a `.joblib` file — no API or
frontend change.

### 5.4 Model availability policy

`FarmIQ-rag/models/` is gitignored (`models/`, `*.joblib` in `.gitignore`), and the
repository historically shipped **no trained model files** — only datasets and
preprocessing artefacts. The adapter therefore handles absence explicitly:

| Domain                  | No model file present                                                                                                          | Model file present |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------ |
| crop, fertilizer, yield | **HTTP 501**                                                                                                                   | real prediction    |
| irrigation              | **rule-based baseline** from `rule_based_baseline.json` (irrigate if soil moisture < 30) — a documented, pre-existing artefact | real prediction    |

`GET /api/health/ml` reports availability per domain. Training real models is one
command: `python -m ml.train_models`, which reads the existing `train.csv` files
and writes `model.joblib` per domain.

### 5.5 Input validation

`ml/validation.py` is the semantic validation layer. It distinguishes two very
different kinds of "odd" value, because conflating them is what makes agricultural
software annoying to use:

| Category       | Source of truth                                                                            | Consequence                                                                  |
| -------------- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| **`invalid`**  | `SUPPORTED_RANGES` — hard physical/agronomic bounds (e.g. soil pH `0–14`, N `0–200 kg/ha`) | **HTTP 422, prediction blocked**                                             |
| **`unusual`**  | `training_ranges()` — the actual min/max of the raw dataset the model was trained on       | HTTP 200 **with a warning**                                                  |
| **`advisory`** | Static                                                                                     | Always returned: training-range membership does not guarantee field accuracy |

Three rules are enforced by tests:

1. **Never clamp, never mutate.** A value of `N = 900` is rejected, not silently
   reduced to `200`. A unit test asserts the input dictionary is byte-identical
   after validation.
2. **Missing and non-numeric are invalid**, not zero.
3. **`invalid` and `unusual` are separate arrays.** "pH 9.5 is outside what the
   model has seen" (unusual) is not the same message as "pH 15 is not a possible
   soil pH" (invalid).

`GET /api/predictions/schema/{domain}` exposes both range sets so React can mirror
the checks client-side before submitting — the same rules, defined once on the
server.

### 5.6 Top-3 crop recommendations

`_rank_classifications()` in the adapter reads the model's **real**
`predict_proba` output and returns up to three ranked entries:

```json
{
  "rank": 1,
  "crop": "rice",
  "score": 0.98,
  "score_type": "probability",
  "score_label": "Model probability (RandomForest class-vote fraction)"
}
```

Three honesty rules apply:

- **`predict_proba` is required.** If the loaded estimator has no such method
  (e.g. `LinearSVC`), the response is `recommendations: null` with
  `score_type: null`, and the UI explains the limitation. No ranking score is
  relabelled as a "probability".
- **Scores are labelled for what they are.** For a RandomForest, `predict_proba`
  is the mean class-vote fraction across trees — a real model output, but not a
  calibrated field-success probability. The label and the standing advisory say so.
- **Fewer than three is valid.** A model with two classes returns two cards; the
  endpoint does not pad the list.

The legacy `details.top` shape is still emitted alongside `recommendations`, so
older frontend code keeps working.

### 5.7 Evaluation methodology and results

`ml/evaluate.py` scores each domain on the **held-out split that already ships in
`datasets/processed/<domain>/test.csv`**. It does **not** re-split the data, which
is what prevents train/test leakage — the split was created by the same
preprocessing script that produced the training data, under one fixed rule:

| Domain     | Split rule                                                      | Source of rule                                       |
| ---------- | --------------------------------------------------------------- | ---------------------------------------------------- |
| crop       | `train_test_split(test_size=0.20, random_state=42, stratify=y)` | `preprocess_crop_recommendation.py`                  |
| fertilizer | `train_test_split(test_size=0.20, random_state=42, stratify=y)` | `preprocess_fertilizer_recommendation.py`            |
| irrigation | `train_test_split(test_size=0.20, random_state=42, stratify=y)` | `preprocess_irrigation.py`                           |
| yield      | **temporal**: `Crop_Year <= 2013` → train, `> 2013` → test      | `preprocess_crop_yield.py`, `TRAIN_YEARS_MAX = 2013` |

Yield uses a temporal split rather than a random one because agricultural yield
has strong time trends; a random split would leak future seasons into training and
inflate the score.

**Results — evaluated 2026-10-26:**

| Domain     | Model                  | n_train | n_test | Classes | Accuracy                        | Precision (macro)           | Recall (macro)             | F1 (macro) |
| ---------- | ---------------------- | ------- | ------ | ------- | ------------------------------- | --------------------------- | -------------------------- | ---------- |
| crop       | RandomForestClassifier | 1760    | 440    | 22      | **0.9955**                      | 0.9957                      | 0.9955                     | **0.9955** |
| fertilizer | RandomForestClassifier | 109     | 28     | 13      | **0.7857**                      | 0.6231                      | 0.6615                     | **0.6282** |
| irrigation | RandomForestClassifier | 120     | 30     | 2       | **0.9667**                      | 0.9808                      | 0.9000                     | **0.9346** |
| yield      | RandomForestRegressor  | 13302   | 6177   | —       | R² 0.8767 (log) · 0.9777 (t/ha) | RMSE 0.338 log · 48.94 t/ha | MAE 0.1954 log · 3.52 t/ha | —          |

**Top-k:** crop top-3 accuracy = **1.0**; fertilizer top-3 accuracy = **0.9643**.
Irrigation top-k is **not reported** — the report states the reason verbatim
(scikit-learn cannot compute top-k when `y_true` is binary but the score matrix is
2-wide) rather than substituting a number.

The crop confusion matrix is a near-perfect diagonal: two misclassifications total
(`blackgram → maize` once, `rice → jute` once) out of 440 samples. Both are
agronomically plausible confusions, which is a mild sanity signal that the model
learned chemistry rather than an artefact.

**Reported caveats** (verbatim from the report, and surfaced in the UI):

- Metrics come from public Kaggle-sourced snapshots, **not** FarmIQ field trials.
- The datasets are limited in size and geographic coverage and may not represent
  real field conditions in any particular location.
- The fertilizer and irrigation test splits are very small (tens of rows), so
  their metrics are indicative only and carry wide uncertainty.
- A test-set score is not a guarantee of accuracy on a real farm.
- The yield model is a regression and has no notion of probability, so no
  confidence figures are reported for it.

**Known non-fatal warning:** the model files were pickled with scikit-learn 1.9.1
and are loaded with 1.9.0, producing `InconsistentVersionWarning`. These are
captured into the report's `load_warnings` field rather than suppressed, so the
version skew stays visible. Installing 1.9.1 clears them.

**Outputs:** `ml/reports/evaluation_report.json` (machine-readable, served live by
the API) and `evaluation_report.md` (human-readable, 22×22 confusion matrix as a
Markdown table — ready for a slide).

---

## 6. Database

### 6.1 Tables

Created by `supabase/migrations/0001_init.sql`:

| Table             | Purpose                                                  |
| ----------------- | -------------------------------------------------------- |
| `profiles`        | App-level user record; maps `mobile → email`, holds role |
| `farms`           | Farm/field records owned by a user                       |
| `devices`         | Paired ESP32-class devices, each with a device token     |
| `sensor_readings` | Time-series readings from devices                        |
| `predictions`     | Audit log of every ML prediction served                  |

Roles are constrained to `farmer`, `farm_manager`, `agricultural_expert`
(`VALID_ROLES` in `config.py`).

### 6.2 Migrations

**`0002_sensor_demo_and_npk.sql`** — additive and idempotent:

```sql
alter table public.sensor_readings
    add column if not exists is_demo      boolean not null default false,
    add column if not exists nitrogen     double precision,
    add column if not exists phosphorous  double precision,
    add column if not exists potassium    double precision,
    add column if not exists ph           double precision;

create index if not exists sensor_readings_owner_demo_idx
    on public.sensor_readings (owner_id, is_demo, created_at desc);
```

No existing data is affected; pre-existing rows default to `is_demo = false`. The
index matches the exact access pattern of `GET /api/sensor-readings?source=…`.

Schemes and the evaluation report are deliberately **not** database tables: one is
static reference content (a JSON file versioned in Git), the other is a generated
artefact. Putting either in Postgres would add migration overhead with no benefit.

---

## 7. Weather integration

**Provider:** Open-Meteo — forecast API plus a geocoding API. Both are key-less.

**Why key-less mattered:** an API key in this feature would have to reach the
browser (the user's location is only known client-side) or be proxied with abuse
risk. Open-Meteo removes the problem entirely: no secret exists to leak, and the
endpoint can stay public.

**Flow:** the client sends either `?lat=&lon=` (from the browser Geolocation API)
or `?location=<place name>` (geocoded server-side).

**The three rainfall concepts are kept strictly separate.** This is the core
correctness requirement of the feature, because the four crop models were trained
on _cumulative seasonal_ rainfall, whereas a weather API reports _instantaneous_
and _forecast_ values:

| Response field        | Meaning                                                         | Used for auto-fill?                         |
| --------------------- | --------------------------------------------------------------- | ------------------------------------------- |
| `current`             | Right now (temperature, humidity, precipitation now)            | **Yes** — temperature, humidity             |
| `historical_rainfall` | Already fallen, summed over `WEATHER_HISTORY_DAYS` (default 30) | **Yes** — rainfall                          |
| `forecast_rainfall`   | Not yet fallen                                                  | No — displayed only, never used as an input |

Each auto-filled value carries `origin` and `is_cumulative` so the UI can label it
("current observation" vs "historical accumulation"), and the rainfall entry
carries a `note` recording that 30-day accumulation is an approximation of the
seasonal total the model was trained on. Current rainfall is **never** substituted
for cumulative seasonal rainfall.

**Degradation.** Every failure path returns **503** with a `hint` telling the user
to type values manually, and the prediction forms remain fully functional. Covered
paths: provider unreachable, geocoding failure, unreadable response body, and
`WEATHER_ENABLED=false`. The app is usable weather-API-free by design, not by
accident.

**Deliberate omission:** no soil-moisture auto-fill. A weather API cannot observe
soil moisture, and the irrigation model expects a raw ADC value from a specific
probe. Inventing a conversion would be fabrication — the sensor simulator supplies
that channel instead.

---

## 8. IoT integration and sensor simulator

### 8.1 Existing hardware protocol (preserved)

ESP32-class devices pair via `POST /api/devices/pair`, which returns a
`device_token` (`secrets.token_urlsafe(32)`). The device then posts readings
authenticated by **device token + `X-Device-Id` header** — no user session needed
on the microcontroller:

```
POST /api/sensor-readings/ingest
Authorization: Bearer <device_token>
X-Device-Id: <device_id>
Content-Type: application/json

{ "device_id": "...", "soil_moisture": 62.0, "temperature": 27.0, "humidity": 71.0 }
```

A user-token path also exists (the `device_id` must belong to that user), and an
optional shared `SENSOR_INGEST_TOKEN` allows admin/test ingestion. **This protocol
and payload structure were not modified.**

### 8.2 The simulator

`app/simulator.py` generates DEMO DATA without touching the hardware path. Design
decisions:

- **Modular by construction.** The simulated payload is a superset of
  `SensorReadingIn`, so a real ESP32 can POST the identical field names to the
  real ingestion endpoint. The simulator is a source, not a fork of the pipeline.
- **Realistic by construction.** Channel ranges are derived from the training
  datasets, and soil moisture is produced twice: a raw ADC-scale value and a
  derived percentage, mirroring how real capacitive probes are read.
- **Configurable.** Per-channel overrides, adjustable noise fraction, and an
  optional seed for reproducible readings (verified by test).
- **Failures are first-class.** Named channels or `"all"` can be failed, producing
  `failed_channels[]` with the corresponding values omitted — so a missing sensor
  is distinguishable from a reading of zero.
- **DEMO marking cannot be omitted.** `is_demo: true` and `label: "DEMO DATA"` are
  set by the generator itself; persistence is opt-in, and when enabled it always
  writes `is_demo = true`.
- **Real records are never overwritten.** Demo rows live in the same table but are
  separated by the `is_demo` column, exposed as
  `GET /api/sensor-readings?source=all|real|demo`. Hardware ingestion now sets
  `is_demo: false` **explicitly in application code** rather than relying only on
  the database default, so the two classes are distinguishable even in a fresh
  environment or a test double.

---

## 9. Government schemes

**Data source:** `FarmIQ-rag/FarmIQ-RAG/data/raw/government_schemes.md`, promoted
into a structured file at `backend/app/data/government_schemes.json`. The original
markdown was used rather than any newly-fetched or generated content.

**Schemes covered:** PM-KISAN, Pradhan Mantri Fasal Bima Yojana (PMFBY), Soil
Health Card, Kisan Credit Card, PMKSY, e-NAM.

**Verification policy — every field carries a status:**

| Status               | Meaning                                        | UI treatment               |
| -------------------- | ---------------------------------------------- | -------------------------- |
| `confirmed`          | Traceable to an official government source     | Green "confirmed" badge    |
| `needs_verification` | Could not be confirmed from an official source | Amber dot + "verify" badge |

Applied to `purpose`, `eligibility`, and **each individual** `benefits[]` and
`application_process[]` entry, so a partly-verified scheme degrades field by field
rather than wholesale.

**No invented content.** Where a scheme is administered offline (KCC through banks,
PMKSY and e-NAM through state departments), the record has **no** `official_links`
and instead carries a `verification_note` explaining why. A test enforces this:
every scheme either has https official links or an explanatory note. Subsidy
amounts and deadlines are absent rather than estimated.

`last_verified: "2026-10-26"` is stored in the file metadata and displayed, so a
reader can judge staleness. Official links: `pmkisan.gov.in`, `pmfby.gov.in`,
`soilhealth.dac.gov.in`.

The requirement explicitly forbade using an LLM or RAG for this feature, so the
data is plain structured JSON served read-only. It is maintainable by editing one
file — no migration, no rebuild.

---

## 10. Pre-existing subsystems (RAG assistant and voice)

These exist in the repository and were **not modified** during the feature work.
They are documented here because they are part of the delivered system.

**RAG assistant.** A separate sub-project at `FarmIQ-rag/FarmIQ-RAG/` with its own
package, virtualenv and `.env`. It owns a knowledge base of curated markdown
(crop practices, symptoms, IPM, irrigation, soil, livestock, market, pesticide
safety, post-harvest, horticulture, weather planning, government schemes) plus its
own retrieval/embedding/LLM pipeline. The backend bridges to it via
`app/rag_service.py` and exposes `POST /api/chat` and `GET /api/chat/status`. The
pipeline is warmed in a background thread at startup so the first question is not
slow.

**Voice.** `POST /api/voice/transcribe` accepts recorded audio and forwards it to
an OpenAI-compatible `/audio/transcriptions` endpoint (Groq Whisper by default) —
this exists because the browser Web Speech API fails with a network error when
Google's service is unreachable and is unimplemented in Firefox/Safari.
`POST /api/voice/speak` synthesises speech with free Microsoft Edge neural voices
via `edge-tts`, because stock Windows and Android installs frequently have no
Marathi (`mr-IN`) or Hindi (`hi-IN`) voice, leaving Devanagari text silent.

The ML feature work in this project introduced **no new LLM dependency and no new
RAG pipeline** — the six features are entirely independent of both subsystems.

---

## 11. Frontend architecture

### 11.1 Navigation

There is **no client-side router**. `App.jsx` is a navigation state machine:
`pages/` holds seven top-level screens and `components/modules/ModuleScreen.jsx`
dispatches on a module `key` to the matching module component.

Trade-off: no browser back/forward and no deep linking, but zero routing
dependencies and a uniform screen shell. This was a pre-existing decision and was
preserved rather than replaced.

### 11.2 Module catalog

`src/data/modules.js` is the single source of truth for the 17 modules — `key`,
`title`, `short`, `group`, `color`, `icon`. Both the browse view
(`ModuleHub.jsx`) and the renderer (`ModuleScreen.jsx`) read from it, so adding a
screen means adding one catalog entry plus one dispatch case.

Icon names resolve through `ModuleIcon.jsx` against the inline SVG set in
`constants/icons.jsx` — no icon-font or icon-package dependency.

### 11.3 Data fetching

`lib/apiClient.js` centralises every network call (`apiGet`, `apiPost`,
`apiUpload`, `apiPatch`, `apiDelete`, `apiPostBlob`). It attaches the bearer token
and normalises errors so callers can inspect `.status` and `.data` uniformly —
which is what makes the 422/501/503 handling on the prediction screens possible.

`hooks/useApi.js` is a small fetch-on-mount hook returning
`{ data, loading, error, refetch }`. Every new screen added in this project uses
it, which is why loading and error states are consistent across the weather panel,
simulator, schemes and MLOps dashboard without duplicated boilerplate.

### 11.4 Modules added or substantially changed in the enhancement round

| Component             | Feature                                                                                                                          |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `WeatherAssist.jsx`   | Weather auto-fill panel: location entry, "Use my location", Refresh, loading/error states, separate rainfall tiles               |
| `SensorSimulator.jsx` | Demo ↔ Connected-sensors switch, overrides, noise/seed, failure injection, opt-in persistence                                    |
| `Schemes.jsx`         | Collapsible scheme cards with per-field confirmation badges                                                                      |
| `MlopsDashboard.jsx`  | Stat tiles, toggleable confusion matrix, caveats, "not evaluated" cards                                                          |
| `MlModule.jsx`        | Rewritten to add: local mirror of server validation, weather auto-fill merge, 422 field-level errors, top-3 recommendation cards |

### 11.5 API base URL

`src/config/api.js` is the only place the backend URL is defined, read from
`VITE_API_BASE_URL` at build time with a `http://127.0.0.1:8001` fallback. This is
mandatory for Android, where `127.0.0.1` refers to the device itself.

---

## 12. Android packaging (Capacitor)

`capacitor.config.ts` declares `appId: com.farmiq.app`, `appName: FarmIQ`, and
`webDir: dist`. `npx cap sync android` copies the Vite build into
`android/app/src/main/assets/public` and updates the native plugin registrations.

**Cleartext HTTP during development.** The backend runs on plain HTTP while the
Capacitor WebView shell is served over HTTPS. Three settings make this work:
`allowMixedContent: true` in the Capacitor config,
`android/app/src/main/res/xml/network_security_config.xml` permitting cleartext,
and the matching `networkSecurityConfig` / `usesCleartextTraffic` attributes in
`AndroidManifest.xml`. For production the backend should be served over HTTPS and
the network security config tightened.

**API base URL per target** — this is the one build-time variable that must change
between environments:

| Target            | `VITE_API_BASE_URL`                                       |
| ----------------- | --------------------------------------------------------- |
| Web dev (browser) | `http://127.0.0.1:8001` (default)                         |
| Android emulator  | `http://10.0.2.2:8001` (`10.0.2.2` maps to host loopback) |
| Physical device   | `http://<LAN-IP>:8001`, e.g. `http://192.168.1.10:8001`   |
| Production        | `https://api.yourdomain.com`                              |

**Build pipeline:** Vite build → `cap sync` → Gradle. The Gradle build compiles
Capacitor core plus the three plugins (app, speech-recognition, text-to-speech),
resolves AndroidX, dexes, and packages a debug APK signed with the debug keystore.

**Status:** `cap sync` succeeds and the Android web assets are current. A full
`assembleDebug` was attempted and executed 128 Gradle tasks through compilation and
dexing before failing at the packaging stage with `There is not enough space on
the disk` — a host disk-space problem, not a code fault. An APK has **not** yet
been produced.

---

## 13. Environment variables

### Backend — `backend/.env`

Loaded by `pydantic-settings` from `.env` (case-insensitive, extra keys ignored).
Defaults in `config.py` mean only Supabase credentials are strictly required.

| Variable                    | Required | Default                                                                   | Purpose                                                                |
| --------------------------- | -------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `SUPABASE_URL`              | **Yes**  | `""`                                                                      | Project URL                                                            |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes**  | `""`                                                                      | Server-side privileged access — **never** in frontend code             |
| `SUPABASE_ANON_KEY`         | No       | `""`                                                                      | Available for anon-scoped calls                                        |
| `ENVIRONMENT`               | No       | `development`                                                             | `production` switches off the permissive localhost/LAN CORS regex      |
| `FRONTEND_ORIGINS`          | No       | `localhost:5173, 127.0.0.1:5173, capacitor://localhost, http://localhost` | CORS allow-list                                                        |
| `CORS_ORIGIN_REGEX`         | No       | `""`                                                                      | Explicit origin regex; takes precedence over `FRONTEND_ORIGINS`        |
| `RATE_LIMIT_ENABLED`        | No       | `true`                                                                    | In-process token-bucket limiter (`app/rate_limit.py`)                  |
| `TRUST_PROXY_HEADERS`       | No       | `false`                                                                   | Honour the rightmost `X-Forwarded-For` hop; enable only behind a proxy |
| `LOG_LEVEL`                 | No       | `INFO`                                                                    | Application logger level                                               |
| `FARMIQ_ML_PROCESSED_PATH`  | No       | `../FarmIQ-rag/datasets/processed`                                        | Preprocessing artefacts                                                |
| `FARMIQ_ML_MODELS_PATH`     | No       | `../FarmIQ-rag/models`                                                    | Trained `.joblib` files                                                |
| `FARMIQ_ML_RAW_PATH`        | No       | `../FarmIQ-rag/datasets/raw`                                              | Unscaled data (correct source for averages)                            |
| `FARMIQ_RAG_PATH`           | No       | `../FarmIQ-rag/FarmIQ-RAG`                                                | RAG sub-project location                                               |
| `SENSOR_INGEST_TOKEN`       | No       | `""`                                                                      | Optional shared secret for device ingestion                            |
| `WEATHER_ENABLED`           | No       | `true`                                                                    | `false` → endpoint returns 503                                         |
| `WEATHER_BASE_URL`          | No       | `https://api.open-meteo.com/v1`                                           | Forecast API                                                           |
| `WEATHER_GEOCODING_URL`     | No       | `https://geocoding-api.open-meteo.com/v1`                                 | Geocoding API                                                          |
| `WEATHER_TIMEOUT_SECONDS`   | No       | `8.0`                                                                     | Outbound timeout                                                       |
| `WEATHER_HISTORY_DAYS`      | No       | `30`                                                                      | Days of past rainfall summed for auto-fill                             |
| `STT_API_KEY`               | No       | `""`                                                                      | Enables server-side transcription; empty → browser STT only            |
| `STT_BASE_URL`              | No       | `https://api.groq.com/openai/v1`                                          | OpenAI-compatible STT endpoint                                         |
| `STT_MODEL`                 | No       | `whisper-large-v3`                                                        | Transcription model                                                    |
| `STT_TIMEOUT_SECONDS`       | No       | `60`                                                                      | Transcription timeout                                                  |
| `TTS_ENABLED`               | No       | `true`                                                                    | Server-side speech synthesis                                           |
| `TTS_TIMEOUT_SECONDS`       | No       | `30`                                                                      | Synthesis timeout                                                      |
| `TTS_VOICE_MR`              | No       | `mr-IN-AarohiNeural`                                                      | Marathi neural voice                                                   |
| `TTS_VOICE_EN`              | No       | `en-IN-NeerjaNeural`                                                      | Indian-English neural voice                                            |

### Frontend — `.env` (project root) or shell environment

| Variable            | Required | Default                 | Purpose                                  |
| ------------------- | -------- | ----------------------- | ---------------------------------------- |
| `VITE_API_BASE_URL` | No       | `http://127.0.0.1:8001` | Backend base URL, baked in at build time |

**No weather API key exists.** `WEATHER_*` variables are configuration only — the
provider is key-less, so there is no secret to rotate or leak.

### Development vs production

Settings are read once, at import time, into a cached `Settings` object
(`config.py` → `get_settings()`), so the same code runs in both environments and
only the values differ:

| Setting                        | Development                           | Production                                    |
| ------------------------------ | ------------------------------------- | --------------------------------------------- |
| `ENVIRONMENT`                  | `development` (default)               | `production`                                  |
| CORS origins                   | Dev default list **plus** a LAN regex | `FRONTEND_ORIGINS` only — no implicit origins |
| `FRONTEND_ORIGINS`             | `http://localhost:5173`, …            | The deployed site origin(s)                   |
| `TRUST_PROXY_HEADERS`          | `false` — a client could spoof XFF    | `true` — Render overwrites `X-Forwarded-For`  |
| `RATE_LIMIT_ENABLED`           | `true`                                | `true`                                        |
| ML/RAG paths                   | `../FarmIQ-rag/...` (relative)        | Absolute `/app/FarmIQ-rag/...` (container)    |
| `VITE_API_BASE_URL` (frontend) | `http://127.0.0.1:8001` (fallback)    | The backend's public HTTPS URL                |

`RATE_LIMIT_ENABLED=false` is intended **only** for trusted load testing; it is
never set in `render.yaml`. See [§19](#19-production-deployment) for the exact
per-service variable list.

---

## 14. Build and run

### 14.1 First-time setup

```powershell
# ── Database ────────────────────────────────────────────────────────
# In the Supabase SQL editor, run all four migrations in order:
#   backend/supabase/migrations/0001_init.sql
#   backend/supabase/migrations/0002_sensor_demo_and_npk.sql
#   backend/supabase/migrations/0003_farming_methods.sql
#   backend/supabase/migrations/0004_farm_coordinates.sql

# ── Backend ─────────────────────────────────────────────────────────
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env      # then fill SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

# ── ML models (models/ is gitignored — required before predictions work) ──
python -m ml.train_models        # writes ../FarmIQ-rag/models/<domain>/model.joblib
python -m ml.evaluate            # writes ml/reports/evaluation_report.json + .md

# ── Frontend ────────────────────────────────────────────────────────
cd ..
npm install
```

### 14.2 Daily development

```powershell
# Terminal 1 — API
cd backend; .\.venv\Scripts\activate; uvicorn app.main:app --reload --port 8001

# Terminal 2 — web app
npm run dev                      # http://localhost:5173
```

Interactive API docs: **http://127.0.0.1:8001/docs**

### 14.3 All npm scripts

```powershell
npm run dev        # Vite dev server (5173)
npm run build      # production build → dist/
npm run preview    # serve the production build
npm run test       # Vitest, single run (43 tests / 5 files)
npm run test:watch # Vitest in watch mode
npm run format     # oxfmt

npm run cap:sync   # build + npx cap sync
npm run cap:open   # open the Android project in Android Studio
npm run android    # build + sync + open (one shot)
npm run assets     # regenerate launcher/splash assets
```

Backend tests run from `backend/` and need no credentials or network (the Supabase
client is faked in `tests/conftest.py`):

```powershell
cd backend; .\.venv\Scripts\activate
python -m pytest -q            # 198 tests
python -m pytest -q tests/test_ml_adapter.py   # one module
```

### 14.4 Android

```powershell
# Emulator
$env:VITE_API_BASE_URL="http://10.0.2.2:8001"; npm run build; npx cap sync android
# Then either:
npx cap open android                       # Android Studio GUI
# or headlessly:
cd android
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug                # → android/app/build/outputs/apk/debug/
```

For a physical device, use your LAN IP and bind the backend to all interfaces:
`uvicorn app.main:app --host 0.0.0.0 --port 8001`.

### 14.5 Health checks

```powershell
Invoke-WebRequest http://127.0.0.1:8001/api/health     -UseBasicParsing   # DB connectivity
Invoke-WebRequest http://127.0.0.1:8001/api/health/ml  -UseBasicParsing   # model availability
Invoke-WebRequest http://127.0.0.1:8001/api/simulator/config              # simulator readiness
Invoke-WebRequest http://127.0.0.1:8001/api/schemes                       # scheme data
Invoke-WebRequest http://127.0.0.1:8001/api/chat/status                   # RAG readiness
```

---

## 15. Testing

### 15.1 Strategy

`backend/tests/conftest.py` provides an in-memory fake of the Supabase
query-builder and auth APIs (`FakeClient` / `FakeQuery`). The suite therefore runs
**with no credentials and no network**, in CI-friendly fashion. Fixtures:

| Fixture                       | Provides                                                            |
| ----------------------------- | ------------------------------------------------------------------- |
| `fake_client`                 | Seeded in-memory Supabase double; `seed_profile()`, `auth_header()` |
| `app_client`                  | FastAPI `TestClient` wired to the fake, with settings cache cleared |
| `ml_tmp_models`               | Temporary models directory so tests can drop real `.joblib` files   |
| `_reset_ml_adapter` (autouse) | Clears the adapter singleton between tests                          |

Tests that need a genuine model train a **real** scikit-learn estimator into
`ml_tmp_models` — e.g. `RandomForestClassifier` for the top-3 tests and
`LinearSVC` to prove the "no `predict_prob` → report the limitation" path. Nothing
is stubbed at the ML boundary.

### 15.2 Results

Measured on the current tree (2026-10-28):

```
python -m pytest -q      →  198 passed in 30.56s   (0 warnings)
npm run test             →  43 passed (5 files) in 24.50s
npm run build            →  ✓ built, no warnings
```

Backend — 18 modules, 198 tests (collected counts):

| Module                    | Tests | Focus                                                                                                                                                       |
| ------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_voice.py`           | 43    | transcription/synthesis, language fallbacks, provider-down handling                                                                                         |
| `test_simulator.py`       | 18    | DEMO labelling, seed reproducibility, overrides, failure injection, persist requires device, cross-user device rejected, demo rows separated from real rows |
| `test_reverse_geocode.py` | 16    | Photon lookup, malformed upstream, coordinate validation, timeouts                                                                                          |
| `test_farming.py`         | 15    | organic/modern/integrated comparison, transition plan, auth required, unknown crop                                                                          |
| `test_rate_limit.py`      | 12    | class classification, `X-Forwarded-For` trust, per-class bucket isolation, health exemption, disable switch, bucket eviction, 429 carries CORS headers      |
| `test_validation.py`      | 11    | supported-range rejection, missing/non-numeric input, valid-but-unusual, **payload not mutated**, 422 blocks prediction                                     |
| `test_ml_adapter.py`      | 10    | **feature order re-derived from the shipped artefacts**, per-domain model availability, `ModelNotAvailableError` → 501, irrigation rule-based fallback      |
| `test_chat.py`            | 10    | RAG status, auth requirement, provider-down behaviour                                                                                                       |
| `test_recommendations.py` | 9     | 3 ranked real probabilities, non-increasing and within [0,1], `LinearSVC` → limitation reported, endpoint schema parity                                     |
| `test_weather.py`         | 8     | three rainfall concepts separate, auto-fill uses history not forecast, provider down → 503 + hint, disabled, missing location → 400                         |
| `test_auth.py`            | 7     | login/register/token verification, password policy, duplicate email                                                                                         |
| `test_farms.py`           | 7     | owner-scoped CRUD, coordinate bounds → 422                                                                                                                  |
| `test_mlops.py`           | 6     | auth required, methodology + caveats disclosed, real crop metrics, confusion matrix sums to sample count, **report served from disk without recomputing**   |
| `test_schemes.py`         | 6     | metadata/legend/cautions, links are https or explained, every field carries a status, category filter, 404                                                  |
| `test_sensors.py`         | 6     | device-token ingestion, ownership, demo vs hardware separation                                                                                              |
| `test_users.py`           | 6     | profile read/update, role defaults, authorisation                                                                                                           |
| `test_predictions.py`     | 5     | end-to-end prediction contract per domain                                                                                                                   |
| `test_health.py`          | 3     | `/api/health`, `/api/health/ml`, deployment probe shape                                                                                                     |

Frontend — 5 modules, 43 tests (Vitest + jsdom):

| Module                                                  | Tests | Focus                                                                                                                                                         |
| ------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/lib/apiClient.test.js`                             | 13    | error contract (`.status`, `detail`), transport-error translation, abort deadline via fake timers, GET de-duplication, a failed shared request frees its slot |
| `src/lib/geolocation.test.js`                           | 10    | permission states, unsupported browser, timeout mapping                                                                                                       |
| `src/components/modules/OrganicFarmingAdvisor.test.jsx` | 9     | load → submit → render comparison, 422 mapped onto form fields                                                                                                |
| `src/components/modules/FarmManager.test.jsx`           | 6     | location capture, typed label preserved, permission denied leaves the form usable, clearing the captured point                                                |
| `src/components/modules/WeatherAssist.test.jsx`         | 5     | farm point used without a permission prompt, manual entry, error states                                                                                       |

The suite is warning-free (`-rw` reports no warnings summary). The
`PytestConfigWarning: Unknown config option: asyncio_mode` recorded in earlier
builds came from running without `pytest-asyncio` installed; it is now a declared
dependency, so the `asyncio_mode` option in `pytest.ini` is registered rather than
unknown.

### 15.3 What tests do not cover

Being explicit about the gap: the suite validates the **API contract, data
integrity and frontend data/error handling**, not the rendered UI. React screens
are otherwise verified by a successful production build plus manual end-to-end
checks. There is no automated test that drives the Android build, no browser-level
(Playwright/Selenium) end-to-end suite, and no load or soak test — the rate
limiter is exercised with a monkeypatched rule rather than sustained traffic.

---

## 16. Engineering rules applied

The non-negotiable constraints of this work, and how each was satisfied:

| Rule                                                         | Implementation                                                                                       |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| **No fabricated predictions, scores, weather or metrics**    | Real models via `predict_proba`; metrics from real test splits; live weather; HTTP 501 when no model |
| **No invented confidence**                                   | Scores labelled with their true nature; `null` + explanation when `predict_proba` is unavailable     |
| **Never silently clamp or mutate input**                     | Validation rejects; a unit test asserts the payload is unchanged                                     |
| **Distinguish invalid from unusual**                         | Separate `invalid[]` and `unusual[]` arrays with different severities and messages                   |
| **Keep the app usable when an API is down**                  | Weather 503 + manual-entry hint; prediction forms unaffected                                         |
| **Never misrepresent simulated data as hardware**            | `is_demo`/`label` set by the generator; hardware path explicitly writes `is_demo: false`             |
| **Preserve the existing hardware protocol**                  | ESP32 device-token + `X-Device-Id` ingestion untouched; the simulator payload is a superset          |
| **Reuse existing architecture and components**               | Code-based routing, `useApi`, `apiClient`, `ModuleShared`, module catalog — all reused               |
| **No LLM/RAG for the schemes feature**                       | Static verified JSON, read-only endpoint                                                             |
| **Secrets in env vars only**                                 | `config.py` / `VITE_API_BASE_URL`; service-role key never leaves the backend                         |
| **Reuse the existing database, migrate only when necessary** | One additive migration; schemes and the evaluation report are files, not tables                      |
| **Preserve auth and authorisation**                          | Supabase Auth + owner-scoped `db.py` + RLS backstop unchanged                                        |
| **Production-ready, no placeholders**                        | Zero TODOs and zero mock buttons in delivered code                                                   |
| **JavaScript, not TypeScript**                               | All frontend source is `.jsx`/`.js`                                                                  |

---

## 17. Known limitations

These are deliberate, documented trade-offs — not oversights.

1. **Rainfall auto-fill is an approximation.** The models were trained on
   _cumulative seasonal_ rainfall; the API supplies 30-day accumulation. The
   response carries a `note` and the UI labels it, rather than presenting it as an
   equivalent figure.
2. **No soil-moisture auto-fill.** Unobservable from weather data; the simulator
   supplies the channel.
3. **Fertilizer and irrigation metrics rest on small test splits** (28 and 30
   rows). Indicative only.
4. **Irrigation top-k accuracy is unavailable** on this split and is reported as a
   stated reason, not a number.
5. **Yield has no confidence figures** — it is a regression model.
6. **Models and the evaluation report are not committed.** `models/` and
   `*.joblib` are gitignored, so `python -m ml.train_models` is a required local
   step. Without it the crop/fertilizer/yield endpoints return 501 by design.
7. ~~**scikit-learn version skew** produces `InconsistentVersionWarning`.~~
   **Resolved:** the artefacts were serialised with scikit-learn 1.9.0, so
   `requirements.txt` now pins the exact version (`scikit-learn==1.9.0` rather
   than a `>=` floor) and the suite runs with zero warnings. Bump the pin only
   together with regenerating the artefacts via `FarmIQ-rag/src/preprocess_*.py`.
8. **No client-side router.** State-driven navigation means no deep linking and no
   browser back/forward.
9. **Migrations have not been verified against a live Supabase instance** —
   tests use an in-memory double, so `0002`–`0004` must be applied to the hosted
   database before simulator persistence, `?source=demo`, the organic-farming
   advisor and farm coordinates work in production.
10. **No Android APK yet.** `cap sync` succeeds; `assembleDebug` ran 128 tasks
    before the host ran out of disk space at the packaging stage.
11. **No automated Android build test.** Frontend unit tests now exist
    (Vitest + jsdom, 43 tests — see §15.2), but nothing exercises the Gradle or
    `cap sync` path.

---

## 18. Deliberately not implemented

The optional features were scoped out to protect the mandatory ones, and each is
blocked by a concrete missing input rather than by time alone:

| Feature                                     | Blocker                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Crop disease identification from images** | No trained disease model exists anywhere in the repository, and no labelled image dataset is present. An `ImageAnalysis.jsx` module exists to host it, but shipping it without a trained _and evaluated_ model would mean fabricated predictions. Requires training a model on a labelled dataset (e.g. PlantVillage) first. |
| **Market prices**                           | No market-price data source is integrated — the repository contains only descriptive markdown on the subject. Adding it needs either a provider key or a verified public API; an unverified scraper would not be reliable and was rejected.                                                                                  |
| **SMS / WhatsApp alerts**                   | Requires provider credentials (Twilio / Meta) and a notification-preference surface, neither of which exists. Without credentials a "Send alert" button would be a mock, which the project rules forbid.                                                                                                                     |

---

## 19. Production deployment

### 19.1 Chosen platforms

| Layer           | Platform                                      | Why                                                                                                                                                                                                                                             |
| --------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend        | Render **Static Site** (free)                 | The app is a static bundle — no server rendering — so a CDN-backed static host is the cheapest correct fit. Built from source with `npm ci && npm run build`, published from `./dist`, with an SPA rewrite to `/index.html`.                    |
| Backend         | Render **Web Service**, Docker runtime (free) | The image must contain the sibling `FarmIQ-rag/` folder (preprocessed artefacts, model directory, RAG requirements). A buildpack cannot copy a sibling directory; a `Dockerfile` can, and pinning `python:3.12-slim` removes interpreter drift. |
| Database + auth | Supabase (managed PostgreSQL + Auth)          | Already the project's provider. No change.                                                                                                                                                                                                      |

Both services are declared in one `render.yaml` blueprint, so the deployment is
reproducible from the repository rather than assembled by hand in a dashboard.
Neither service requires a paid plan.

### 19.2 Artefacts that define the deployment

| File                                    | Role                                                                                                                                                                       |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Dockerfile` (repo root)                | Backend image: `python:3.12-slim`; copies `FarmIQ-rag` → `/app/FarmIQ-rag` and `backend` → `/app/backend`; installs both requirements files; `EXPOSE 8001`; starts uvicorn |
| `.dockerignore`                         | Keeps the image small (`node_modules`, `.venv`, `dist`, `android`, `__pycache__`) and **excludes `.env` / `backend/.env`** so no local secret can be baked into the image  |
| `render.yaml`                           | Declares both services, their variables (`sync: false` for secrets, filled in the dashboard), the health-check path and the SPA rewrite                                    |
| `backend/.env.example`, `.env.example`  | Document every variable; contain no real values                                                                                                                            |
| `backend/supabase/migrations/0001…0004` | The schema, applied once by hand (§19.5)                                                                                                                                   |

### 19.3 Port binding

The container listens on `0.0.0.0:8001` — `EXPOSE 8001` plus
`CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]`.
Binding `0.0.0.0` rather than `127.0.0.1` is required: a loopback-only bind is
unreachable from the platform's router. Render detects the port from `EXPOSE`, so
no `PORT` variable is needed — but if the port is ever changed, `EXPOSE`, the
`CMD` and `healthCheckPath` must change together. Local development uses the same
8001 for consistency (`8000` is frequently occupied on Windows).

### 19.4 Environment variables per service

**Backend** (`farmiq-api`) — set in the Render dashboard, Environment tab.
⊘ = secret; never commit it, never place it in the frontend.

| Variable                      | Production value                                                            |
| ----------------------------- | --------------------------------------------------------------------------- |
| `SUPABASE_URL` ⊘              | `https://<project-ref>.supabase.co`                                         |
| `SUPABASE_SERVICE_ROLE_KEY` ⊘ | From Supabase → Project Settings → API (server-side only)                   |
| `SUPABASE_ANON_KEY` ⊘         | Same page (only needed for anon-scoped calls)                               |
| `ENVIRONMENT`                 | `production` — disables the permissive localhost/LAN CORS regex             |
| `FRONTEND_ORIGINS`            | `https://<web-service>.onrender.com,capacitor://localhost,http://localhost` |
| `TRUST_PROXY_HEADERS`         | `true` — Render terminates TLS and overwrites `X-Forwarded-For`             |
| `LOG_LEVEL`                   | `INFO`                                                                      |
| `FARMIQ_ML_PROCESSED_PATH`    | `/app/FarmIQ-rag/datasets/processed` (absolute, matches the image layout)   |
| `FARMIQ_ML_MODELS_PATH`       | `/app/FarmIQ-rag/models`                                                    |
| `FARMIQ_ML_RAW_PATH`          | `/app/FarmIQ-rag/datasets/raw`                                              |
| `STT_API_KEY` ⊘               | Optional — enables server-side transcription; blank disables it             |
| `STT_BASE_URL`, `STT_MODEL`   | `https://api.groq.com/openai/v1`, `whisper-large-v3`                        |

Not set in production: `RATE_LIMIT_ENABLED` (stays `true`), `SENSOR_INGEST_TOKEN`
(only if ESP32 devices are deployed), `WEATHER_*` (key-less provider — no secret
exists to configure).

**Frontend** (`farmiq-web`) — one variable, read at build time:

| Variable            | Production value                                                 |
| ------------------- | ---------------------------------------------------------------- |
| `VITE_API_BASE_URL` | The backend's public URL, e.g. `https://farmiq-api.onrender.com` |

> `VITE_*` values are compiled into the browser bundle and are therefore **public
> by definition**. Never put a secret in one. Because it is baked at build time,
> changing this variable requires a frontend rebuild, not just a restart.

### 19.5 Deployment steps

1. **Create the Supabase project** and note the project URL, anon key and
   service-role key (Project Settings → API).
2. **Apply the migrations** in the Supabase SQL editor, in order:
   `0001_init.sql`, `0002_sensor_demo_and_npk.sql`,
   `0003_farming_methods.sql`, `0004_farm_coordinates.sql`.
3. **Push the repository to GitHub** — Render deploys from a Git remote.
4. In Render: **New → Blueprint**, select the repository. Render reads
   `render.yaml` and proposes two services, `farmiq-api` and `farmiq-web`.
5. **Deploy `farmiq-api` first** and fill in the `sync: false` variables from
   §19.4. Note its public URL once healthy.
6. **Set `VITE_API_BASE_URL`** on `farmiq-web` to that URL, then deploy it.
7. **Set `FRONTEND_ORIGINS`** on `farmiq-api` to the web service's URL (plus the
   Capacitor origins if the Android shell is in use), then restart the API so the
   new CORS allow-list is loaded.

The order matters: the frontend build needs the API URL, and the API's CORS
allow-list needs the frontend URL, so the API is deployed before the site is
configured, and CORS is finalised last.

### 19.6 Post-deploy verification

```powershell
Invoke-WebRequest https://<api>.onrender.com/api/health/live  -UseBasicParsing  # 200 {"status":"alive"}
Invoke-WebRequest https://<api>.onrender.com/api/health       -UseBasicParsing  # 200, database connected
Invoke-WebRequest https://<api>.onrender.com/api/health/ready -UseBasicParsing  # 503 only if the DB is unreachable
Invoke-WebRequest https://<api>.onrender.com/api/health/ml    -UseBasicParsing  # which ML domains have artefacts/models
```

Then open the deployed site, sign in, and confirm no CORS error appears in the
browser console. The health check configured on the service is
`/api/health/live` — a liveness probe only, deliberately: Render restarts a
service that fails its health check, and a database outage is not repaired by a
container restart. Use `/api/health/ready` for readiness when checking by hand.

### 19.7 Known deployment caveats

1. **Predictions return 501 in a fresh deployment.** `models/*.joblib` are
   gitignored and the image does not run `python -m ml.train_models`, so the
   crop/fertilizer/yield endpoints report "model not available" (HTTP 501) until
   trained artefacts are supplied. This is the documented behaviour (§5.4), not a
   deployment fault — but it must be a conscious decision: train the models and
   bake/attach them, or accept that those three endpoints are unavailable in the
   hosted environment. Verify with `/api/health/ml`.
2. **The rate limiter is per process.** Buckets live in instance memory, so with
   more than one API instance the effective limit is _per instance_. Fine for a
   single-instance free-plan deployment; a shared store would be required to make
   the limit global.
3. **Free-tier instances sleep.** Render's free plan spins an idle service down,
   so the first request after a quiet period is slow. This is a cost/first-byte
   trade-off, not a bug.
4. **Capacitor Android builds still need `VITE_API_BASE_URL`** pointing at a
   device-reachable URL (§12, §14.4) — the web deployment's value is not
   automatically correct for the emulator.

---

### Document maintenance

| Section      | Update when                                                            |
| ------------ | ---------------------------------------------------------------------- |
| §3, §13, §14 | Dependencies, env vars or scripts change                               |
| §5.5         | `SUPPORTED_RANGES` / preprocessing changes                             |
| §5.7, §15.2  | Re-run `python -m ml.evaluate` / `pytest -q` and paste the new numbers |
| §6.2         | A migration is added                                                   |
| §17          | A limitation is closed or a new one accepted                           |
| §19          | The hosting platform, service names or deployment config change        |
| §9           | Scheme data is re-verified — also update `last_verified` in the JSON   |
