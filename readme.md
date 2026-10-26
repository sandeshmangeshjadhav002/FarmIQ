# FarmIQ

An AI-powered agricultural advisory platform that helps farmers with crop recommendations, irrigation scheduling, soil health monitoring, market intelligence, IoT sensor management, and more — all through a mobile-first web app.

---

## Project Structure

```
FarmIQ-main/
├── backend/                  # Python FastAPI backend
│   ├── .env                  # Database configuration
│   ├── venv/
│   │   └── main.py           # FastAPI app (all routes, models, DB logic)
│   └── start_server.bat      # Launches the server on port 8000
│
└── FarmIQ-main/              # React/Vite frontend
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx            # Root component — navigation state machine
        ├── data/modules.js    # Master data: module catalog and all demo content
        ├── constants/
        │   ├── languages.js   # 11 supported language labels
        │   └── icons.jsx      # SVG icon definitions
        ├── pages/             # 7 top-level screen components
        └── components/        # common/, layout/, modules/ sub-directories
```

---

## Tech Stack

### Frontend
| Library | Version | Purpose |
|---|---|---|
| React | ^19.0.0 | UI framework |
| Vite | ^8.0.5 | Dev server and bundler |
| Tailwind CSS | ^4.0.0 | Utility-first styling |
| TypeScript | ^5.7.0 | Type checking (dev only, source is JSX) |

### Backend
| Library | Purpose |
|---|---|
| FastAPI | ASGI web framework |
| Supabase (Postgres + Auth) | Database + authentication (JWT verified server-side) |
| supabase-py | Server-side Supabase client (service-role + token verification) |
| Pydantic v2 | Request/response validation |
| scikit-learn / joblib | ML adapter: loads existing encoders/scalers + optional models |
| uvicorn | ASGI server |

> The backend was rebuilt from the old single-file SQLAlchemy+bcrypt app into a
> structured FastAPI + Supabase package. See **[backend/README.md](backend/README.md)**
> for setup, the full API reference, ML integration, Supabase migration, and tests.

---

## Prerequisites

- **Node.js** (v18+) and **npm**
- **Python** (3.11+)
- **PostgreSQL** (running locally on port 5432)

---

## Getting Started

### 1. Set up the database

Create a PostgreSQL database named `FarmIQ`:

```sql
CREATE DATABASE "FarmIQ";
```

### 2. Configure the backend environment

Edit `backend/.env` to match your PostgreSQL credentials:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=FarmIQ
DB_USER=postgres
DB_PASSWORD=your_password
```

### 3. Start the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install fastapi "uvicorn[standard]" sqlalchemy psycopg pydantic[email] bcrypt python-dotenv
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Or use the provided script:

```bash
cd backend
start_server.bat
```

The API will be available at `http://127.0.0.1:8001`. Tables are created automatically on first startup.

### 4. Start the frontend

```bash
cd FarmIQ-main
npm install
npm run dev
```

The app will be available at `http://localhost:5173`.

---

## Features

### Authentication
- **Register** — full name, email, mobile number (with country code), role, and password. Password must be 8+ characters with at least one uppercase letter and one number.
- **Login** — mobile number + password. Supports 11 country codes including India (+91), USA (+1), UK (+44), and others.
- **Continue without account** — available from the login screen for demo access.

### Supported Roles
- `farmer`
- `farm_manager`
- `agricultural_expert`

### Module Hub (17 modules)

| Group | Module |
|---|---|
| **Manage** | Farm Management, Farming Calendar, Alerts & Notifications, Reports & Analytics, Device Management, Profile & Settings |
| **Plan** | Crop Recommendation, Fertilizer Recommendation, Yield Prediction, Market Intelligence |
| **Monitor** | Smart Irrigation, Soil Health, IoT Sensor Monitoring, Crop Image Analysis |
| **Learn** | Knowledge Center |
| **Administration** | MLOps Dashboard, Administration & Roles |

Modules with fully custom UIs: Farm Management, Crop Image Analysis, Farming Calendar, Knowledge Center, Profile & Settings, Device Management.

All other modules display structured demo data (metrics + detail rows) via a shared generic layout.

### AI Chat Assistant
Chat interface with quick-action shortcuts for crop advice, irrigation, fertilizer, and market prices. Currently renders a demo seed conversation — LLM integration is not yet connected.

### IoT Sensor Integration
Backend API accepts and stores sensor readings (soil moisture, temperature, humidity) keyed by `device_id`. The frontend Device Management module shows paired devices and their live status.

### Language Support
11 Indian and international languages available in the settings panel: English, Hindi, Marathi, Telugu, Tamil, Kannada, Gujarati, Bengali, Punjabi, Malayalam, and Odia.

---

## API Reference

Base URL: `http://127.0.0.1:8001`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Backend health check |
| `GET` | `/api/health` | Database connectivity check |
| `POST` | `/api/auth/register` | Register a new user (returns 201) |
| `POST` | `/api/auth/login` | Sign in with mobile + password |
| `POST` | `/api/sensor-readings/` | Submit a new sensor reading |
| `GET` | `/api/sensor-readings/` | Fetch the latest 100 sensor readings |

Interactive API docs (Swagger UI): `http://127.0.0.1:8000/docs`

### Register payload example
```json
{
  "full_name": "Ravi Kumar",
  "email": "ravi@example.com",
  "mobile": "+919876543210",
  "role": "farmer",
  "password": "Secure123"
}
```

### Sensor reading payload example
```json
{
  "device_id": "esp32-field-hub-01",
  "soil_moisture": 62.5,
  "temperature": 27.3,
  "humidity": 71.0
}
```

---

## Development Notes

- **No client-side router** — all navigation is state-driven in `App.jsx`. Browser back/forward and deep linking are not supported.
- **No auth session persistence** — there is no JWT or token storage. A page refresh will return the user to the login screen.
- **All module data is static demo content** — only auth and sensor readings actually talk to the backend. Features like yield prediction, market prices, and crop recommendations are populated with hardcoded demo values from `src/data/modules.js`.
- **Password hashing** — bcrypt with 6 rounds in development. Increase `BCRYPT_ROUNDS` to 12+ before deploying to production.
- **CORS** — the backend allows requests from `localhost:5173` (Vite dev server) only. Update the `allow_origins` list in `main.py` for production deployments.

---

## Android (Capacitor)

This project is wrapped with [Capacitor](https://capacitorjs.com/) so the same
Vite/React app ships as a native Android app. The native project lives in
`android/` and the web build is copied into `android/app/src/main/assets/public`.

### Prerequisites
- **Android Studio** (Hedgehog / 2023.1 or newer recommended)
- **JDK 17+** (bundled with recent Android Studio)
- An Android device (with USB debugging) **or** an emulator

### Important: the backend URL
`127.0.0.1` does **not** work on a phone/emulator — it points at the device
itself, not your dev machine. The API base URL is read from the `VITE_API_BASE_URL`
env var at build time (see `src/config/api.js` and `.env.example`).

| Target | `VITE_API_BASE_URL` |
|---|---|
| Android emulator | `http://10.0.2.2:8001` (10.0.2.2 maps to host loopback) |
| Physical device (same Wi-Fi) | `http://<your-LAN-IP>:8001`, e.g. `http://192.168.1.10:8001` |
| Production | `https://api.yourdomain.com` |

When using a physical device, also start the backend on all interfaces so the
phone can reach it, and ensure the FastAPI `allow_origins` in `main.py`
includes the origin the WebView uses (`capacitor://localhost` / `http://localhost`):

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

### Build & run on Android

```bash
# 1. Build the web app with the backend URL the device can reach (PowerShell):
$env:VITE_API_BASE_URL="http://10.0.2.2:8001"; npm run build

# 2. Sync the web build + Capacitor config into the native project:
npx cap sync android

# 3. Open in Android Studio and run on a device/emulator:
npx cap open android
```

Or use the convenience scripts:

```bash
npm run cap:sync   # build + npx cap sync
npm run cap:open   # open the android project in Android Studio
npm run android    # build + sync + open (one shot)
```

### Why HTTP works during development
The backend runs on plain HTTP. Android blocks cleartext traffic by default
since API 28, so the project ships:
- `android/app/src/main/res/xml/network_security_config.xml` — permits cleartext.
- `android:networkSecurityConfig` + `android:usesCleartextTraffic` in
  `AndroidManifest.xml`.
- `allowMixedContent: true` in `capacitor.config.ts` (the WebView shell is HTTPS).

For production, serve the backend over HTTPS and tighten the network security
config (remove `cleartextTrafficPermitted="true"` or scope it to your domain).

### Rebuilding after frontend changes
Any change to the React app must be re-synced before it shows up in Android:

```bash
npm run cap:sync
```

Then re-run from Android Studio (or `npx cap run android`).

---

## Scripts

### Frontend
```bash
npm run dev       # Start development server
npm run build     # Production build
npm run preview   # Preview the production build
npm run format    # Format code with oxfmt
npm run cap:sync  # Build + sync web assets into the Android project
npm run cap:open  # Open the Android project in Android Studio
npm run android   # Build + sync + open Android Studio (one shot)
```

### Backend
```bash
uvicorn main:app --reload          # Start with hot reload
uvicorn main:app --host 0.0.0.0    # Expose on all interfaces
```
