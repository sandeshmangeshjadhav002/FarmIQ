<div align="center">

<img src="docs/screenshots/03_home_screen.png" width="280" alt="FarmIQ Home Screen"/>

# 🌾 FarmIQ — Intelligent Smart Agriculture Platform

**AI-powered agricultural decision support for Indian farmers**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-v4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![Capacitor](https://img.shields.io/badge/Capacitor-8-119EFF?logo=capacitor&logoColor=white)](https://capacitorjs.com)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white)](https://supabase.com)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://python.org)

[**🚀 Live Demo**](#-live-demo) · [**📸 Screenshots**](#-screenshots) · [**⚡ Quick Start**](#-quick-start) · [**📖 Docs**](#-documentation)

</div>

---

## 🌟 What is FarmIQ?

FarmIQ transforms a smartphone into a full-featured farm advisor. It combines **real ML models**, **live IoT sensor data**, **weather forecasts**, and an **AI assistant** to give Indian farmers personalised, evidence-based recommendations in English and Marathi.

> Built for hackathons. Deployable on Android. Backed by real data.

---

## 🚀 Live Demo

| Platform | Link |
|---|---|
| 🔌 **Backend API** | [farmiq-api-hpss.onrender.com](https://farmiq-api-hpss.onrender.com/api/health) |
| 📱 **Android APK** | [Download debug APK](https://github.com/sandeshmangeshjadhav002/FarmIQ-copy/releases) |
| 📸 **Screenshots** | [See every screen](#-screenshots) |

> 🌐 The web app isn't hosted publicly yet — [deploy your own](#-deploy-to-production) (Render + Vercel). The live backend above runs on Render's free tier, so the first request may take up to a minute to wake it.

**Demo account** (read-only, pre-seeded with farm data):
```
Mobile : +91 98765 43210
Password: Demo@1234
```

> No account needed — tap **"Continue without account"** on the login screen to explore.

---

## 📸 Screenshots

<table>
<tr>
<td align="center" width="33%">
  <img src="docs/screenshots/01_login_screen.png" width="220" alt="Login"/>
  <br/><b>Login</b>
</td>
<td align="center" width="33%">
  <img src="docs/screenshots/03_home_screen.png" width="220" alt="Home Dashboard"/>
  <br/><b>Home Dashboard</b>
</td>
<td align="center" width="33%">
  <img src="docs/screenshots/04_home_action_plan.png" width="220" alt="Today's Action Plan"/>
  <br/><b>Today's Action Plan</b>
</td>
</tr>
<tr>
<td align="center">
  <img src="docs/screenshots/06_ai_chat.png" width="220" alt="AI Chat Assistant"/>
  <br/><b>AI Chat Assistant</b>
</td>
<td align="center">
  <img src="docs/screenshots/05_module_hub.png" width="220" alt="Module Hub"/>
  <br/><b>Module Hub (22 tools)</b>
</td>
<td align="center">
  <img src="docs/screenshots/07_farm_screen.png" width="220" alt="Farm Screen"/>
  <br/><b>Farm Screen</b>
</td>
</tr>
<tr>
<td align="center">
  <img src="docs/screenshots/09_crop_recommendation.png" width="220" alt="Crop Recommendation"/>
  <br/><b>Crop Recommendation (ML)</b>
</td>
<td align="center">
  <img src="docs/screenshots/11_smart_irrigation.png" width="220" alt="Smart Irrigation"/>
  <br/><b>Smart Irrigation</b>
</td>
<td align="center">
  <img src="docs/screenshots/10_fertilizer.png" width="220" alt="Fertilizer Advice"/>
  <br/><b>Fertilizer Recommendation</b>
</td>
</tr>
<tr>
<td align="center">
  <img src="docs/screenshots/12_organic_farming.png" width="220" alt="Organic Farming"/>
  <br/><b>Organic Farming Advisor</b>
</td>
<td align="center">
  <img src="docs/screenshots/13_drought_management.png" width="220" alt="Drought Management"/>
  <br/><b>Drought Management</b>
</td>
<td align="center">
  <img src="docs/screenshots/14_yield_prediction.png" width="220" alt="Yield Prediction"/>
  <br/><b>Yield Prediction</b>
</td>
</tr>
<tr>
<td align="center">
  <img src="docs/screenshots/16_iot_sensors.png" width="220" alt="IoT Sensors"/>
  <br/><b>IoT Sensor Monitoring</b>
</td>
<td align="center">
  <img src="docs/screenshots/17_govt_schemes.png" width="220" alt="Government Schemes"/>
  <br/><b>Government Schemes</b>
</td>
<td align="center">
  <img src="docs/screenshots/20_mlops_dashboard.png" width="220" alt="MLOps Dashboard"/>
  <br/><b>MLOps Dashboard</b>
</td>
</tr>
</table>

---

## ✨ Features

### 🤖 AI-Powered Decision Engine
- **Farm Action Plan** — daily prioritised recommendations combining weather, sensor data, and ML predictions
- **AI Chat Assistant** — natural conversation in English and Marathi; understands greetings, farm questions, and crop advice
- **Groq LLM** (llama-3.3-70b-versatile) with RAG knowledge base
- **Voice input** (Web Speech API + server-side Groq Whisper fallback)
- **Text-to-speech** in Marathi and English (edge-tts neural voices, no API key)

### 🌱 Crop & Soil Intelligence
| Feature | Model | Accuracy |
|---|---|---|
| Crop Recommendation | RandomForest (22 crops) | Real metrics via `/api/mlops/evaluation` |
| Fertilizer Recommendation | RandomForest (7 types) | Real metrics |
| Yield Prediction | RandomForest Regressor | Real metrics |
| Irrigation Decision | RandomForest + rule baseline | Real metrics |

### 🌿 New: Organic vs Modern Farming
Compare organic, conventional, and integrated farming methods side-by-side:
- Nutrient management strategies
- Input cost estimates
- Labour and water requirements
- Environmental impact
- Transition plans

### 💧 New: Drought Management
- Severity assessment from soil moisture + rainfall + ML
- 6-category recommendations (sowing, irrigation, mulching, crop alternatives, dry spell, finance)
- Live Open-Meteo weather + 7-day forecast
- ICAR-sourced guidance, with source citations

### 📡 IoT Integration
- ESP32/ESP8266 device pairing with device tokens
- Real-time soil moisture, temperature, humidity
- Sensor freshness alerts (stale / offline detection)
- Interactive Sensor Simulator for demos

### 🌦️ Weather (Open-Meteo — free, no API key)
- Current conditions auto-filled in all ML forms
- Historical 30-day rainfall for cumulative crop models
- 7-day forecast clearly labelled as unconfirmed

### 🏛️ Government Schemes
- PM-KISAN, PMFBY, Soil Health Card, PM Kisan Samman Nidhi
- Eligibility, benefits, documents, application process
- Official source links and last-verified dates

### 📊 MLOps Dashboard
- Real evaluation metrics on held-out test sets
- Confusion matrices, F1, accuracy, RMSE
- Model version, training methodology, caveats

---

## 🏗️ Architecture

```
📱 Android App (Capacitor)
    └── React 19 + Tailwind CSS v4 (Vite 8)
          └── REST API calls
                └── FastAPI (Python 3.14 + uvicorn)
                      ├── Supabase (PostgreSQL + Auth + RLS)
                      ├── scikit-learn ML models (.joblib)
                      ├── Open-Meteo weather API (free, key-less)
                      ├── ChromaDB + sentence-transformers (RAG)
                      ├── Groq Whisper (speech-to-text)
                      └── edge-tts (text-to-speech)
```

### Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, Tailwind CSS v4, Vite 8 |
| **Mobile** | Capacitor 8 (Android), Speech Recognition, TTS |
| **Backend** | FastAPI 0.162, Python 3.14, Uvicorn |
| **Database** | Supabase (PostgreSQL), Row Level Security |
| **ML Models** | scikit-learn 1.9, RandomForest (4 domains) |
| **AI/LLM** | Groq (llama-3.3-70b), edge-tts, Whisper |
| **Weather** | Open-Meteo (free, key-less) |
| **RAG** | ChromaDB, sentence-transformers (multilingual) |
| **Deployment** | Render (backend), Vercel (frontend) |

---

## ⚡ Quick Start

### Prerequisites
- Node.js 18+ and npm
- Python 3.12+ (or 3.14)
- A free [Supabase](https://supabase.com) project
- A free [Groq](https://console.groq.com) API key

### 1. Clone
```bash
git clone https://github.com/sandeshmangeshjadhav002/FarmIQ-copy.git
cd FarmIQ-copy
```

### 2. Backend setup
```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -r ..\FarmIQ-rag\FarmIQ-RAG\requirements.txt
```

Copy `.env.example` to `.env` and fill in:
```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
STT_API_KEY=gsk_...          # Groq API key
```

Apply the database migration in Supabase SQL editor:
```sql
-- Run backend/supabase/migrations/0001_init.sql
-- Run backend/supabase/migrations/0002_drought_farming.sql
```

Train the ML models (one-time):
```powershell
python -m ml.train_models
```

Start the backend:
```powershell
python -m uvicorn app.main:app --reload --port 8001
```

### 3. Frontend setup
```powershell
# In a new terminal, from the project root
npm install
npm run dev
```

Open http://localhost:5173 — register an account and start exploring.

### 4. Android build (optional)
```powershell
# Point the app at the backend (use your LAN IP for a physical device)
$env:VITE_API_BASE_URL="http://10.0.2.2:8001"   # emulator
npm run build
npx cap sync android
npx cap open android    # opens Android Studio
```

---

## 🚢 Deploy to Production

### Backend → Render (free tier)

The repo includes `render.yaml` and a `Dockerfile`. Connect your GitHub repo to [Render](https://render.com) — it reads the blueprint automatically.

Set these environment variables in the Render dashboard:
```
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
STT_API_KEY          # Groq
FRONTEND_ORIGINS     # your Vercel URL
```

### Frontend → Vercel (free tier)
```bash
npm install -g vercel
vercel --prod
```

Set `VITE_API_BASE_URL=https://farmiq-api-hpss.onrender.com` in Vercel project settings.

### Android → Play Store
```powershell
$env:VITE_API_BASE_URL="https://farmiq-api-hpss.onrender.com"
npm run build
npx cap sync android
# In Android Studio: Build → Generate Signed Bundle → AAB
```

---

## 📂 Project Structure

```
FarmIQ/
├── src/                        # React frontend
│   ├── pages/                  # 7 top-level screens
│   ├── components/
│   │   ├── common/             # Icon, Button, TextInput, Logo
│   │   ├── layout/             # ScreenShell, BottomNav, DesktopNav
│   │   └── modules/            # 22 feature modules (lazy-loaded)
│   ├── hooks/                  # useApi, useSpeech
│   ├── lib/                    # apiClient.js (auth-aware fetch)
│   └── data/modules.js         # Module catalog & static data
│
├── backend/
│   ├── app/
│   │   ├── routers/            # 18 FastAPI routers
│   │   ├── agent_service.py    # LLM-driven AI agent
│   │   ├── decision_engine.py  # Farm action plan (deterministic)
│   │   ├── drought_service.py  # Drought assessment engine
│   │   ├── farming_service.py  # Organic vs modern farming
│   │   ├── farm_context_manager.py
│   │   └── weather.py          # Open-Meteo integration
│   ├── ml/
│   │   ├── adapter.py          # Loads & runs .joblib models
│   │   ├── train_models.py     # Optional: retrain from CSVs
│   │   └── evaluate.py         # Real evaluation metrics
│   └── supabase/migrations/    # SQL schema files
│
├── FarmIQ-rag/
│   ├── datasets/raw/           # Source CSVs (Kaggle datasets)
│   ├── datasets/processed/     # Scalers, encoders, train/test splits
│   ├── models/                 # Trained .joblib model files
│   └── FarmIQ-RAG/             # RAG pipeline (ChromaDB + LLM)
│
├── android/                    # Capacitor Android project
├── docs/screenshots/           # App screenshots for README
├── Dockerfile                  # Production Docker image
└── render.yaml                 # Render deployment blueprint
```

---

## 🌍 API Reference

Base URL: `http://127.0.0.1:8001`  
Interactive docs: `http://127.0.0.1:8001/docs`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check + DB status |
| `POST` | `/api/auth/register` | Register (201) |
| `POST` | `/api/auth/login` | Sign in → tokens |
| `GET` | `/api/farms` | List farms |
| `GET` | `/api/dashboard/plan` | 🆕 Farm Action Plan |
| `POST` | `/api/predictions/crop` | Crop ML prediction |
| `POST` | `/api/predictions/fertilizer` | Fertilizer ML prediction |
| `POST` | `/api/predictions/irrigation` | Irrigation ML prediction |
| `POST` | `/api/predictions/yield` | Yield ML prediction |
| `POST` | `/api/agent/chat` | 🆕 LLM-driven AI agent chat |
| `POST` | `/api/farming-methods/compare` | 🆕 Organic vs modern farming |
| `POST` | `/api/drought/assess` | 🆕 Drought assessment |
| `GET` | `/api/weather/current` | Live weather data |
| `GET` | `/api/mlops/evaluation` | Real model metrics |
| `GET` | `/api/demo/farms` | Hackathon demo farms |
| `POST` | `/api/demo/plan` | Demo action plan |

---

## 📊 Datasets

| Domain | Source | Rows | License |
|---|---|---|---|
| Crop Recommendation | [Kaggle — atharvaingle](https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset) | 2,200 | CC0 Public Domain |
| Fertilizer Recommendation | [Kaggle — gdabhishek](https://www.kaggle.com/datasets/gdabhishek/fertilizer-prediction) | ~1,000 | CC BY-NC-SA |
| Crop Yield India | [Kaggle — abhinand05](https://www.kaggle.com/datasets/abhinand05/crop-production-in-india) | 246,000 | CC0 Public Domain |
| Irrigation (IoT) | [GCEKIoT Community](https://github.com/GCEKIoTCommunity/Irrigation-Dataset) | ~5,000 | Academic (MHRD-NPIU) |

---

## 🧪 Tests

```powershell
cd backend
.\.venv\Scripts\activate
pytest tests/ -q       # 229 tests including agent, drought, decision engine
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m "Add my feature"`
4. Push and open a Pull Request

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgements

- [ICAR](https://icar.org.in) — agricultural guidelines used in drought and irrigation recommendations
- [Open-Meteo](https://open-meteo.com) — free weather API
- [Groq](https://groq.com) — fast LLM inference (llama-3.3-70b)
- [Supabase](https://supabase.com) — open-source Firebase alternative
- [Capacitor](https://capacitorjs.com) — cross-platform mobile framework

---

<div align="center">

**Made with ❤️ for Indian farmers**

⭐ Star this repo if FarmIQ helped you!

</div>
