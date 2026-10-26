# FarmIQ Backend (FastAPI + Supabase + ML)

FastAPI backend that connects the existing React frontend, Supabase
(Auth + Postgres), and the existing FarmIQ-ML preprocessing artefacts.

## Architecture

```
backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, lifespan, router registration
│   ├── config.py            # env-driven settings (Supabase creds, ML paths, CORS)
│   ├── logging_conf.py      # centralised logging
│   ├── supabase_client.py   # privileged service-role client (dependency)
│   ├── auth.py              # verify Supabase access token; current_user dependency
│   ├── schemas.py           # Pydantic request/response models (exact ML feature order)
│   ├── db.py                # data-access layer; EVERY query filters by owner_id
│   ├── errors.py            # centralised exception handlers
│   └── routers/             # health, auth, users, farms, devices, sensors, predictions, dashboard
├── ml/
│   ├── adapter.py           # loads existing encoders/scalers + optional model; predicts
│   └── train_models.py      # OPTIONAL: trains real models from the existing datasets
├── tests/                   # pytest (mocked Supabase — no creds needed)
└── supabase/migrations/0001_init.sql
```

**Auth model.** The frontend posts `mobile` + `password` to
`/api/auth/login` and `/api/auth/register` (its existing contract — unchanged).
The backend maps mobile→email via the `profiles` table, uses Supabase Auth as
the identity provider (creates/verifies users server-side with the
service-role key), and returns the user object **plus** `access_token`/
`refresh_token`. The frontend captures the access token
(`src/lib/apiClient.js`) and sends it as `Authorization: Bearer …` on
protected requests.

**Authorisation.** A single privileged client is created with the
service-role key, which bypasses Row Level Security. Because of that, every
`db.py` function filters by the authenticated user's id explicitly. RLS
policies in the migration are a defence-in-depth backstop. The service-role
key never leaves the backend.

## Setup

### 1. Python environment
```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Supabase
1. Create a Supabase project. In **Project Settings → API** copy the Project
   URL, `anon` key, and `service_role` key.
2. Run the migration in the Supabase SQL editor (or `supabase db push`):
   `supabase/migrations/0001_init.sql`. This creates `profiles`, `farms`,
   `devices`, `sensor_readings`, `predictions` with RLS policies.
3. Copy `.env.example` to `.env` and fill in:
   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_ANON_KEY=...
   SUPABASE_SERVICE_ROLE_KEY=...     # SERVER SIDE ONLY
   SUPABASE_JWT_SECRET=...            # optional
   FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,capacitor://localhost,http://localhost
   ```

### 3. Run
```powershell
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8001
```
Interactive docs: http://127.0.0.1:8001/docs

## ML integration

The adapter reuses the **existing** preprocessing artefacts in
`../FarmIQ-rag/datasets/processed/<domain>/` (scalers, encoders, feature
metadata, label maps). It applies the exact feature order and preprocessing
from `FarmIQ-rag/src/preprocess_*.py`.

**Important — no trained model files exist in the repo** (only preprocessing
artefacts and datasets). Per the project rules, predictions are NOT fabricated:
* `crop`, `fertilizer`, `yield` return **HTTP 501** until a model file is
  present.
* `irrigation` falls back to the existing **rule-based baseline**
  (`rule_based_baseline.json`: irrigate if soil moisture < 30) — a real,
  documented artefact, not a fabricated prediction.

To enable live predictions for all four domains, run the optional trainer
(uses the existing preprocessed `train.csv` files — real models, not dummies):
```powershell
cd backend
.\.venv\Scripts\activate
python -m ml.train_models
```
This writes `model.joblib` under `../FarmIQ-rag/models/<domain>/`. Restart the
server (or hit `/api/health/ml`) and the adapter picks them up automatically.
Replace those files with your own models anytime.

Check status any time: `GET /api/health/ml`.

## API reference

Base URL: `http://127.0.0.1:8001`

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/` | – | Backend up |
| GET | `/api/health` | – | DB connectivity |
| GET | `/api/health/ml` | – | ML model availability per domain |
| POST | `/api/auth/register` | – | Register → user + tokens (201) |
| POST | `/api/auth/login` | – | Login (mobile+password) → user + tokens |
| GET | `/api/users/me` | Bearer | Current profile |
| PATCH | `/api/users/me` | Bearer | Update full name |
| GET | `/api/farms` | Bearer | List farms (limit/offset) |
| POST | `/api/farms` | Bearer | Create farm (201) |
| GET/PATCH/DELETE | `/api/farms/{id}` | Bearer | Farm CRUD (owner-scoped) |
| GET | `/api/devices` | Bearer | List devices |
| POST | `/api/devices/pair` | Bearer | Pair a device → returns `device_token` (201) |
| GET/DELETE | `/api/devices/{id}` | Bearer | Device access |
| POST | `/api/sensor-readings/ingest` | Bearer¹ | Ingest a reading (201) |
| GET | `/api/sensor-readings` | Bearer | History (device_id/farm_id/limit/offset) |
| POST | `/api/predictions/crop` | Bearer | Crop recommendation |
| POST | `/api/predictions/fertilizer` | Bearer | Fertilizer recommendation |
| POST | `/api/predictions/yield` | Bearer | Yield estimate (t/ha) |
| POST | `/api/predictions/irrigation` | Bearer | Irrigate? (model or baseline) |
| GET | `/api/predictions` | Bearer | Prediction history (domain/limit/offset) |
| GET | `/api/dashboard/summary` | Bearer | Counts + latest reading |

¹ Sensor ingestion accepts **either** a user Bearer token (the `device_id`
must belong to that user) **or** a device Bearer token sent with an
`X-Device-Id` header (ESP32 devices authenticate with the `device_token`
returned at pairing). An optional `SENSOR_INGEST_TOKEN` env var allows
admin/test ingestion.

### Request examples
Crop:
```json
{ "N": 90, "P": 40, "K": 40, "temperature": 25, "humidity": 80, "ph": 6.5, "rainfall": 200 }
```
Irrigation:
```json
{ "soil_moisture": 20, "soil_temperature": 25, "temperature": 28, "humidity": 65, "crop_days": 10, "crop_type": "Paddy" }
```
Errors are returned as `{ "detail": "…" }` (the shape the frontend already reads).

## ESP32 sensor ingestion

After pairing a device (`POST /api/devices/pair` → keep `device_token`), the
device posts:
```
POST /api/sensor-readings/ingest
Authorization: Bearer <device_token>
X-Device-Id: <device_id>
Content-Type: application/json
{ "device_id": "<device_id>", "soil_moisture": 62.0, "temperature": 27.0, "humidity": 71.0 }
```

## Testing

Tests run without Supabase credentials — a fake client in `tests/conftest.py`
mocks the Supabase query-builder and auth APIs.
```powershell
cd backend
.\.venv\Scripts\activate
pytest -q
```
Covers health, auth (register/login/duplicate/wrong-password/bad-role), farm
CRUD + ownership, sensor ingestion (user-token + device-token + mismatch),
predictions (irrigation baseline, 501 for missing models, history), and the ML
adapter (artefacts load, 501 paths, real model-file load, status).

## Security notes
* Service-role key stays server-side; never referenced by the frontend.
* Every data operation is owner-scoped in `db.py` + RLS policies.
* Device tokens are random `secrets.token_urlsafe(32)`; ingestion verifies
  `device_id` + token (or the shared `SENSOR_INGEST_TOKEN`).
* Input validation via Pydantic field bounds (matching the ML valid ranges).
