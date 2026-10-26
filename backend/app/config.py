"""Application configuration loaded from environment variables.

All Supabase credentials live here and are never sent to the frontend.
Defaults for ML asset paths point at the existing FarmIQ-rag artefacts.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve paths relative to this file so the backend works regardless of CWD.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_ML_PROCESSED = PROJECT_ROOT / "FarmIQ-rag" / "datasets" / "processed"
DEFAULT_ML_MODELS = PROJECT_ROOT / "FarmIQ-rag" / "models"
DEFAULT_ML_RAW = PROJECT_ROOT / "FarmIQ-rag" / "datasets" / "raw"
# Standalone RAG project (its own package, virtualenv and .env live here).
DEFAULT_RAG_PROJECT = PROJECT_ROOT / "FarmIQ-rag" / "FarmIQ-RAG"

VALID_ROLES = {"farmer", "farm_manager", "agricultural_expert"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Supabase ──────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_role_key: str = ""  # SERVER SIDE ONLY — bypasses RLS
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""        # optional local JWT verification fallback

    # ── CORS ──────────────────────────────────────────────────────────
    frontend_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,capacitor://localhost,http://localhost"
    )

    # ── ML artefacts ───────────────────────────────────────────────────
    farmiq_ml_processed_path: str = str(DEFAULT_ML_PROCESSED)
    farmiq_ml_models_path: str = str(DEFAULT_ML_MODELS)
    # Raw (pre-scaling) datasets — used to derive real averages for inputs the
    # farmer did not supply. The processed/*.csv files hold scaled values, so
    # averages must never be taken from them.
    farmiq_ml_raw_path: str = str(DEFAULT_ML_RAW)

    # ── Speech-to-text (server-side transcription) ─────────────────────
    # Chrome/Edge ship the Web Speech API, but it fails with a "network" error
    # when Google's speech service is unreachable, and Firefox/Safari do not
    # implement it at all. The browser records audio and posts it to
    # POST /api/voice/transcribe, which calls an OpenAI-compatible
    # /audio/transcriptions endpoint (Groq Whisper by default).
    stt_api_key: str = ""
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model: str = "whisper-large-v3"
    stt_timeout_seconds: int = 60

    # ── Text-to-speech (server-side synthesis) ─────────────────────────
    # Windows desktops and stock Android devices frequently have no Marathi
    # (mr-IN) or Hindi (hi-IN) voice installed, so the browser's
    # speechSynthesis API and the Android TextToSpeech engine stay silent on
    # Devanagari text. The client posts the answer to POST /api/voice/speak,
    # which synthesises it with the free Microsoft Edge neural voices
    # (edge-tts) and returns MP3 audio. No API key is required, but the
    # server needs outbound internet access.
    tts_enabled: bool = True
    tts_timeout_seconds: int = 30
    tts_voice_mr: str = "mr-IN-AarohiNeural"
    tts_voice_en: str = "en-IN-NeerjaNeural"

    # ── RAG assistant ──────────────────────────────────────────────────
    # Path to the standalone FarmIQ-RAG project (contains src/ and data/).
    farmiq_rag_path: str = str(DEFAULT_RAG_PROJECT)

    # ── Weather (Open-Meteo, no API key required) ──────────────────────
    # Used to auto-fill temperature / humidity / accumulated rainfall in the
    # ML prediction forms. Open-Meteo needs no key; the base URLs are settings
    # so a self-hosted or proxy deployment can be pointed at another host.
    weather_enabled: bool = True
    weather_base_url: str = "https://api.open-meteo.com/v1"
    weather_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1"
    weather_timeout_seconds: float = 8.0
    # How many past days of daily rainfall are summed for the accumulated total.
    weather_history_days: int = 30

    # ── Device ingestion ──────────────────────────────────────────────
    sensor_ingest_token: str = ""  # optional shared secret for ESP32 devices

    # Derived ──────────────────────────────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def ml_processed_dir(self) -> Path:
        return Path(self.farmiq_ml_processed_path)

    @property
    def ml_models_dir(self) -> Path:
        return Path(self.farmiq_ml_models_path)

    @property
    def ml_raw_dir(self) -> Path:
        return Path(self.farmiq_ml_raw_path)

    @property
    def stt_configured(self) -> bool:
        return bool(self.stt_api_key.strip())

    def tts_voice_for(self, language: str) -> str:
        """Neural voice name for a supported language code ("mr" or "en")."""
        return self.tts_voice_mr if language == "mr" else self.tts_voice_en

    @property
    def rag_project_dir(self) -> Path:
        return Path(self.farmiq_rag_path)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Override in tests by calling get_settings.cache_clear()."""
    return Settings()
