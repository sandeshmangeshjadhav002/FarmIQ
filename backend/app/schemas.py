"""Pydantic request/response schemas for the FarmIQ API.

ML input schemas mirror the EXACT feature order and validation ranges defined
by the existing preprocessing scripts in FarmIQ-rag/src/preprocess_*.py, so the
adapter can apply the original encoders/scalers without reshaping.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ─────────────────────────────────────────────────────────────────────────
# Auth & users
# ─────────────────────────────────────────────────────────────────────────

VALID_ROLES = ("farmer", "farm_manager", "agricultural_expert")


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    mobile: str = Field(min_length=8, max_length=20)
    role: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "full_name": "Ravi Kumar",
            "email": "ravi@example.com",
            "mobile": "+919876543210",
            "role": "farmer",
            "password": "Secure123",
        }
    })


class UserLogin(BaseModel):
    mobile: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class UserProfile(BaseModel):
    """The user object the React frontend stores after login/register."""
    id: str
    full_name: str
    email: EmailStr
    mobile: str
    role: str
    created_at: Optional[str] = None


class AuthResponse(BaseModel):
    """Returned by /api/auth/login and /api/auth/register.

    The existing frontend reads ``full_name``/``detail`` and stores the whole
    body as the user object. ``access_token``/``refresh_token`` are added for
    protected requests (the frontend captures them via the new api client).
    """
    id: str
    full_name: str
    email: EmailStr
    mobile: str
    role: str
    created_at: Optional[str] = None
    access_token: str = ""
    refresh_token: str = ""


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=200)


# ─────────────────────────────────────────────────────────────────────────
# Farms
# ─────────────────────────────────────────────────────────────────────────

class FarmBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=300)
    area_value: Optional[float] = Field(default=None, ge=0)
    area_unit: str = Field(default="acres", max_length=20)
    irrigation_type: str = Field(default="drip", max_length=50)
    soil_type: Optional[str] = Field(default=None, max_length=100)
    current_crop: Optional[str] = Field(default=None, max_length=100)


class FarmCreate(FarmBase):
    pass


class FarmUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    location: Optional[str] = Field(default=None, min_length=1, max_length=300)
    area_value: Optional[float] = Field(default=None, ge=0)
    area_unit: Optional[str] = Field(default=None, max_length=20)
    irrigation_type: Optional[str] = Field(default=None, max_length=50)
    soil_type: Optional[str] = Field(default=None, max_length=100)
    current_crop: Optional[str] = Field(default=None, max_length=100)


class FarmOut(FarmBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_id: str
    created_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────────────────────────────────

DEVICE_CONFIGS = ("soil_sensor", "weather_node", "tank_level", "generic")


class DevicePair(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    farm_id: Optional[str] = None
    config: str = Field(default="soil_sensor", max_length=50)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_id: str
    name: str
    farm_id: Optional[str] = None
    config: str
    device_token: str
    is_online: bool = True
    last_seen_at: Optional[str] = None
    created_at: Optional[str] = None


class DeviceTokenOut(BaseModel):
    device_id: str
    device_token: str


# ─────────────────────────────────────────────────────────────────────────
# Sensor readings
# ─────────────────────────────────────────────────────────────────────────

class SensorReadingIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    soil_moisture: Optional[float] = Field(default=None, ge=0, le=100)
    soil_temperature: Optional[float] = Field(default=None, ge=-50, le=100)
    temperature: Optional[float] = Field(default=None, ge=-50, le=100)
    humidity: Optional[float] = Field(default=None, ge=0, le=100)
    # Raw capacitive SoilMoisture (0–2000) used by the irrigation model is also
    # accepted via the dedicated field below.
    soil_moisture_raw: Optional[float] = Field(default=None, ge=0, le=2000)


class SensorReadingOut(SensorReadingIn):
    id: str
    farm_id: Optional[str] = None
    owner_id: str
    created_at: str


# ─────────────────────────────────────────────────────────────────────────
# ML predictions — inputs mirror the exact preprocessing feature order
# ─────────────────────────────────────────────────────────────────────────

class CropPredictionRequest(BaseModel):
    """crop_recommendation: N,P,K,temperature,humidity,ph,rainfall"""
    N: float = Field(ge=0, le=200)
    P: float = Field(ge=0, le=200)
    K: float = Field(ge=0, le=250)
    temperature: float = Field(ge=0, le=55)
    humidity: float = Field(ge=0, le=100)
    ph: float = Field(ge=0, le=14)
    rainfall: float = Field(ge=0, le=3000)


class FertilizerPredictionRequest(BaseModel):
    """fertilizer_recommendation: Temparature,Humidity,Moisture,Nitrogen,
    Potassium,Phosphorous,Soil Type,Crop Type"""
    temparature: float = Field(ge=0, le=55)
    humidity: float = Field(ge=0, le=100)
    moisture: float = Field(ge=0, le=100)
    nitrogen: float = Field(ge=0, le=200)
    potassium: float = Field(ge=0, le=250)
    phosphorous: float = Field(ge=0, le=200)
    soil_type: str = Field(min_length=1, max_length=50)
    crop_type: str = Field(min_length=1, max_length=50)


class YieldPredictionRequest(BaseModel):
    """crop_yield_india: State_Name,Season,Crop,Crop_Year,Area,
    Annual_Rainfall,Fertilizer,Pesticide"""
    state_name: str = Field(min_length=1, max_length=100)
    season: str = Field(min_length=1, max_length=50)
    crop: str = Field(min_length=1, max_length=100)
    crop_year: float = Field(ge=1900, le=2100)
    area: float = Field(gt=0)
    annual_rainfall: float = Field(default=0, ge=0)
    fertilizer: float = Field(default=0, ge=0)
    pesticide: float = Field(default=0, ge=0)


class IrrigationPredictionRequest(BaseModel):
    """irrigation: SoilMoisture,SoilTemperature,Temperature,Humidity,CropDays,CropType"""
    soil_moisture: float = Field(ge=0, le=2000)
    soil_temperature: float = Field(default=0, ge=0, le=60)
    temperature: float = Field(default=0, ge=0, le=60)
    humidity: float = Field(default=0, ge=0, le=100)
    crop_days: float = Field(default=0, ge=0, le=365)
    crop_type: str = Field(default="Paddy", min_length=1, max_length=50)


class PredictionResponse(BaseModel):
    domain: str
    prediction: Any
    source: str = "model"  # "model" | "baseline"
    label: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class PredictionHistoryItem(BaseModel):
    id: str
    owner_id: str
    domain: str
    input: dict[str, Any]
    output: dict[str, Any]
    source: str
    created_at: str


# ─────────────────────────────────────────────────────────────────────────
# AI assistant (RAG chat)
# ─────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """A farmer's question for the RAG assistant.

    ``ml_results`` optionally carries FarmIQ ML outputs (e.g.
    ``{"predicted_crop": "soybean", "fertilizer_recommendation": "DAP"}``).
    Only non-null fields are used and the model's values are never modified.

    ``history`` optionally carries the last few conversation turns
    (``{"role": "farmer"|"assistant", "text": "..."}``) so that follow-up
    questions referring back to an earlier subject can be answered.
    """
    message: str = Field(min_length=1, max_length=1000)
    ml_results: Optional[dict[str, Any]] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    history: Optional[list[dict[str, Any]]] = Field(default=None, max_length=20)


class ChatSource(BaseModel):
    source: str
    page: Optional[int] = None
    similarity: float
    snippet: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource] = []
    retrieval_status: str = "OK"          # OK | BELOW_THRESHOLD | EMPTY_INDEX
    retrieval_message: str = ""
    llm_used: bool = False
    ml_context_provided: bool = False
    warnings: list[str] = []


class ChatStatusResponse(BaseModel):
    """Assistant readiness, used by the frontend to show a friendly state."""
    available: bool
    indexed: bool = False
    index_chunks: int = 0
    llm_configured: bool = False
    embedding_model: Optional[str] = None
    message: str = ""


# ─────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    farms: int
    devices: int
    devices_online: int
    recent_readings: int
    predictions: int
    latest_reading: Optional[dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────────────────
# Voice assistant  (POST /api/voice/chat)
# ─────────────────────────────────────────────────────────────────────────

SUPPORTED_VOICE_LANGUAGES = ("mr", "en")   # mr = Marathi, en = English

INTENT_LABELS = (
    "crop_recommendation",
    "fertilizer_recommendation",
    "irrigation",
    "yield_prediction",
    "sensor_query",
    "navigation_help",
    "knowledge",   # answered by the RAG assistant (no dedicated ML model)
    "unknown",     # only when the assistant is unavailable
)


class VoiceChatRequest(BaseModel):
    """Request body for POST /api/voice/chat.

    ``message``        – the transcript (Marathi or English text).
    ``language``       – BCP-47 language code: "mr" (Marathi) or "en" (English).
    ``conversation_id``– optional session-level ID; reserved for future history.
    ``context``        – optional dict carrying partial slot values from a
                         previous turn so the backend can continue a multi-turn
                         collection dialogue.
    ``history``        – optional recent conversation turns
                         (``{"role": "farmer"|"assistant", "text": "..."}``) used
                         by the RAG assistant to resolve follow-up references
                         such as "for it" and to keep the answer on topic.
    """
    message: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="mr", pattern=r"^(mr|en)$")
    conversation_id: Optional[str] = Field(default=None, max_length=100)
    context: Optional[dict[str, Any]] = None
    history: Optional[list[dict[str, Any]]] = Field(default=None, max_length=20)


class VoiceChatResponse(BaseModel):
    """Response from POST /api/voice/chat.

    ``response_text``  – farmer-friendly text in the requested language.
    ``language``       – language the response is written in.
    ``intent``         – detected intent label.
    ``follow_up``      – True when the backend is asking for more information.
    ``missing_slots``  – list of field names still needed (for follow-up turns).
    ``prediction``     – included when a model was actually called.
    ``speak``          – True when the client should auto-play TTS.
    """
    response_text: str
    language: str
    intent: str = "unknown"
    follow_up: bool = False
    missing_slots: list[str] = []
    prediction: Optional[dict[str, Any]] = None
    speak: bool = True


# ─────────────────────────────────────────────────────────────────────────
# Voice transcription  (POST /api/voice/transcribe)
# ─────────────────────────────────────────────────────────────────────────

class TranscriptionResponse(BaseModel):
    """Result of server-side speech-to-text.

    ``text``  – recognised transcript ("" when nothing could be recognised).
    ``language`` – language the audio was transcribed as ("mr" or "en").
    ``model`` – the transcription model that produced the text.
    """
    text: str
    language: str = "mr"
    model: str = ""


# ─────────────────────────────────────────────────────────────────────────
# Voice synthesis  (POST /api/voice/speak)
# ─────────────────────────────────────────────────────────────────────────

class SpeechRequest(BaseModel):
    """Request body for POST /api/voice/speak.

    ``text``     – the text to read aloud (Markdown already stripped by the
                   client). Kept in step with VoiceChatRequest.message.
    ``language`` – BCP-47 language code: "mr" (Marathi) or "en" (English).
    """
    text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="mr", pattern=r"^(mr|en)$")
