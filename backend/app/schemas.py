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
    # Optional so the signup form does not have to ask a farmer to classify
    # themselves. Defaults to the most common case; the role is editable later
    # in the profile. The auth router still validates it against VALID_ROLES.
    role: str = Field(default="farmer", min_length=1, max_length=50)
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
    # Role is changeable here so that dropping it from the signup form does not
    # leave "agricultural_expert" unreachable. Validated in the users router.
    role: Optional[str] = Field(default=None, max_length=50)


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
    # Optional precise point. Bounds mirror the DB check constraints; both are
    # set together (a lone latitude is rejected by the database).
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


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
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


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
    # Barometric pressure (hPa) from BME680-type air nodes. Optional because a
    # soil-only probe does not measure it.
    pressure: Optional[float] = Field(default=None, ge=300, le=1100)


class SensorReadingOut(SensorReadingIn):
    id: str
    farm_id: Optional[str] = None
    owner_id: str
    created_at: str
    is_demo: bool = False
    nitrogen: Optional[float] = None
    phosphorous: Optional[float] = None
    potassium: Optional[float] = None
    ph: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────
# Sensor simulator (DEMO mode)
# ─────────────────────────────────────────────────────────────────────────

class SimulatorRequest(BaseModel):
    """Request to generate one simulated reading.

    ``overrides`` forces exact channel values, ``fail`` marks channels as dead
    (``["all"]`` fails everything), ``noise`` adds jitter, and ``seed`` makes the
    output reproducible. ``persist`` (opt-in) also stores it with
    ``is_demo = true`` — real readings are never touched.
    """
    overrides: dict[str, float] = Field(default_factory=dict)
    fail: list[str] = Field(default_factory=list)
    noise: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    persist: bool = False
    device_id: Optional[str] = None


class SimulatedReadingOut(BaseModel):
    is_demo: bool = True
    label: str
    generated_at: str
    seed: Optional[int] = None
    reading: dict[str, float] = {}
    failed_channels: list[str] = []
    notes: list[str] = []
    persisted: bool = False
    record_id: Optional[str] = None
    device_id: Optional[str] = None


class SimulatorConfigOut(BaseModel):
    label: str
    channels: dict[str, dict[str, Any]]
    failure_modes: list[str]
    note: str


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


class CropRecommendation(BaseModel):
    """One ranked crop recommendation.

    ``score`` is the model's own output for this crop and ``score_type`` names
    exactly what that number is (e.g. ``"probability"``), so a ranking score is
    never mislabelled as a probability. Nothing here is invented: values come
    straight from the trained model's ``predict_proba``.
    """
    rank: int
    crop: str
    score: float
    score_type: str
    score_label: str


class ValidationIssue(BaseModel):
    """A single validation message (blocking error or non-blocking warning)."""
    field: str
    label: str
    value: Any = None
    unit: Optional[str] = None
    kind: str
    message: str
    supported_min: Optional[float] = None
    supported_max: Optional[float] = None
    training_min: Optional[float] = None
    training_max: Optional[float] = None


class PredictionResponse(BaseModel):
    """Consistent response shape for all four ML domains.

    ``recommendations`` is populated for classification domains that expose
    ``predict_proba`` (crop, and optionally fertilizer). ``unusual`` carries
    valid-but-out-of-training-range warnings and ``advisory`` the standing
    "training range ≠ field accuracy" disclosure.
    """
    domain: str
    prediction: Any
    source: str = "model"  # "model" | "baseline"
    label: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    recommendations: Optional[list[CropRecommendation]] = None
    score_type: Optional[str] = None
    warnings: list[str] = []
    unusual: list[ValidationIssue] = []
    advisory: Optional[str] = None


class ValidationField(BaseModel):
    """Machine-readable range for one model input field."""
    field: str
    label: str
    type: str
    unit: Optional[str] = None
    supported_min: Optional[float] = None
    supported_max: Optional[float] = None
    training_min: Optional[float] = None
    training_max: Optional[float] = None
    options: Optional[list[str]] = None


class ValidationSchemaResponse(BaseModel):
    """Ranges the frontend uses to warn *before* submitting a prediction."""
    domain: str
    fields: list[ValidationField]
    advisory: str


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
    # True when the farmer's own farm details (name, location, soil, crop,
    # latest sensor reading) were supplied to the assistant as background.
    farm_context_provided: bool = False
    warnings: list[str] = []


class ChatStatusResponse(BaseModel):
    """Assistant readiness, used by the frontend to show a friendly state."""
    available: bool
    indexed: bool = False
    index_chunks: int = 0
    llm_configured: bool = False
    # Which provider/model generates answers (e.g. "huggingface" +
    # "meta-llama/Llama-3.1-8B-Instruct"). Never contains credentials.
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_model: Optional[str] = None
    message: str = ""


# ─────────────────────────────────────────────────────────────────────────
# Weather auto-fill
# ─────────────────────────────────────────────────────────────────────────

class WeatherDailyRain(BaseModel):
    date: str
    precipitation_mm: Optional[float] = None
    rain_mm: Optional[float] = None


class WeatherAutofill(BaseModel):
    """A single suggested form value, with its origin stated explicitly."""
    value: float
    unit: str
    origin: str              # "current observation" | "historical accumulation"
    label: str
    observed_at: Optional[str] = None
    is_cumulative: bool = False
    note: Optional[str] = None


class WeatherLocation(BaseModel):
    name: Optional[str] = None
    latitude: float
    longitude: float
    timezone: Optional[str] = None


class WeatherReverseLocation(BaseModel):
    """A place label resolved from coordinates (used to pre-fill the farm form).

    ``label`` is a convenience the farmer may edit; ``latitude``/``longitude``
    are the values that were actually resolved and remain authoritative.
    ``source`` credits the provider, as its licence requires attribution.
    """
    label: str
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postcode: Optional[str] = None
    latitude: float
    longitude: float
    source: str


class WeatherCurrent(BaseModel):
    observed_at: Optional[str] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    precipitation_mm: Optional[float] = None
    rain_mm: Optional[float] = None
    label: str


class WeatherRainfall(BaseModel):
    days: int
    total_mm: Optional[float] = None
    past_7_days_mm: Optional[float] = None
    daily: list[WeatherDailyRain] = []
    label: str


class WeatherReport(BaseModel):
    """Current conditions plus rainfall history/forecast, all kept separate.

    Deliberately never merges the three rainfall concepts: ``current`` is the
    observation now, ``forecast_rainfall`` rain that has not fallen yet, and
    ``historical_rainfall`` the accumulated total already fallen.
    """
    source: str
    fetched_at: str
    location: WeatherLocation
    current: WeatherCurrent
    forecast_rainfall: WeatherRainfall
    historical_rainfall: WeatherRainfall
    autofill: dict[str, WeatherAutofill] = {}
    notes: list[str] = []


# ─────────────────────────────────────────────────────────────────────────
# Organic vs. modern farming advisor
# ─────────────────────────────────────────────────────────────────────────

class FarmResources(BaseModel):
    """Organic materials the farmer reports as available on the farm."""
    cow_dung: bool = False
    compost: bool = False
    crop_residues: bool = False
    other: list[str] = Field(default_factory=list, max_length=20)


class FarmingContextRequest(BaseModel):
    """Shared request body for the compare + transition-plan endpoints.

    ``preference`` is one of ``organic`` / ``modern`` / ``integrated``.
    ``farm_id`` is optional; when supplied the backend verifies the caller owns
    that farm before using it. ``save`` persists the result as a user-scoped
    plan.
    """
    crop: str = Field(min_length=1, max_length=80)
    location: Optional[str] = Field(default=None, max_length=200)
    soil_type: str = Field(min_length=1, max_length=80)
    area_acres: float = Field(gt=0, le=100_000)
    current_fertilizer: Optional[str] = Field(default=None, max_length=300)
    current_pesticide: Optional[str] = Field(default=None, max_length=300)
    resources: FarmResources = Field(default_factory=FarmResources)
    preference: str = Field(min_length=1, max_length=30)
    farm_id: Optional[str] = Field(default=None, max_length=100)
    save: bool = False


class FarmingOptionsResponse(BaseModel):
    """Options the frontend form needs, served from the curated content."""
    crops: list[str]
    soil_types: list[str]
    preferences: list[dict[str, Any]]
    metadata: dict[str, Any]
    legend: dict[str, str]
    definition_notes: dict[str, str]
    cautions: list[str]


class FarmingPlanSummary(BaseModel):
    id: str
    kind: str
    crop: Optional[str] = None
    preference: Optional[str] = None
    farm_id: Optional[str] = None
    created_at: Optional[str] = None


class FarmingPlanListResponse(BaseModel):
    total: int
    plans: list[FarmingPlanSummary]


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


# ─────────────────────────────────────────────────────────────────────────
# Drought Management & Water Conservation
# ─────────────────────────────────────────────────────────────────────────

DROUGHT_URGENCY = ("critical", "high", "moderate", "low")
DROUGHT_CATEGORIES = (
    "sowing_decision",
    "water_conservation",
    "irrigation_management",
    "crop_alternatives",
    "dry_spell_management",
    "financial_planning",
)


class DroughtAssessmentRequest(BaseModel):
    """Input form for drought management assessment.

    All numeric fields are optional because a farmer may not have access to
    instruments. The backend uses whatever is supplied and states clearly which
    fields were missing.
    """
    # Farm context
    location: str = Field(min_length=1, max_length=200)
    crop: str = Field(min_length=1, max_length=80)
    growth_stage: str = Field(min_length=1, max_length=80)
    soil_type: str = Field(min_length=1, max_length=80)
    area_value: float = Field(gt=0, le=100_000)
    area_unit: str = Field(default="acres", max_length=20)

    # Sowing / crop timeline
    sowing_date: Optional[str] = Field(
        default=None, max_length=20,
        description="ISO date YYYY-MM-DD, or approximate 'Early June'",
    )
    sowing_status: str = Field(
        default="already_sown",
        description="'not_yet_sown' | 'already_sown' | 'germination' | 'tillering'",
        max_length=30,
    )

    # Water situation
    recent_rainfall_mm: Optional[float] = Field(default=None, ge=0, le=3000,
        description="Rainfall in mm over the past 2–3 weeks (farmer-observed)",
    )
    water_availability: str = Field(
        default="limited",
        description="'none' | 'limited' | 'moderate' | 'good'",
        max_length=20,
    )
    irrigation_type: str = Field(
        default="none",
        description="'none' | 'canal' | 'borewell' | 'drip' | 'sprinkler' | 'other'",
        max_length=30,
    )
    irrigation_hours_available: Optional[float] = Field(
        default=None, ge=0, le=24,
        description="Approximate irrigation hours available per day",
    )

    # Budget
    budget_inr: Optional[float] = Field(
        default=None, ge=0,
        description="Approximate available budget in INR (optional)",
    )

    # Fetch weather forecast from Open-Meteo?
    fetch_weather: bool = Field(
        default=True,
        description="Whether to auto-fetch weather forecast for the location",
    )

    # Persist result?
    save: bool = False
    farm_id: Optional[str] = Field(default=None, max_length=100)


class DroughtRecommendationItem(BaseModel):
    """One actionable recommendation in a category."""
    action: str
    reason: str
    urgency: str                           # critical | high | moderate | low
    materials: list[str] = []
    estimated_cost_inr: Optional[str] = None   # always a text range, never a figure
    expected_benefits: list[str] = []
    limitations: list[str] = []
    source: Optional[str] = None           # publication or guideline cited


class DroughtCategory(BaseModel):
    """A grouped set of recommendations under one thematic category."""
    category: str                          # one of DROUGHT_CATEGORIES
    category_label: str
    urgency: str                           # highest urgency among items
    items: list[DroughtRecommendationItem] = []


class DroughtWeatherSummary(BaseModel):
    """Snapshot of weather used in the assessment (never invents data)."""
    fetched: bool = False
    location_resolved: Optional[str] = None
    current_temp_c: Optional[float] = None
    current_humidity_pct: Optional[float] = None
    historical_rain_mm: Optional[float] = None   # past 30 days observed total
    historical_days: Optional[int] = None
    forecast_rain_7d_mm: Optional[float] = None  # next 7 days forecast sum
    forecast_note: str = (
        "Forecast rainfall is not confirmed. Do not act on forecast data alone."
    )
    fetch_error: Optional[str] = None
    data_as_of: Optional[str] = None


class DroughtAssessmentResponse(BaseModel):
    """Full drought assessment response."""
    crop: str
    growth_stage: str
    location: str
    soil_type: str
    area_value: float
    area_unit: str
    sowing_status: str
    water_availability: str
    irrigation_type: str

    # Overall severity assessment
    drought_severity: str          # "none" | "mild" | "moderate" | "severe" | "extreme"
    drought_severity_reason: str

    # Weather snapshot (may be partial or missing)
    weather: DroughtWeatherSummary

    # Categorised recommendations
    categories: list[DroughtCategory] = []

    # RAG-sourced context (advisory text, not executable instructions)
    rag_context: Optional[str] = None
    rag_sources: list[dict[str, Any]] = []
    rag_status: str = "not_attempted"

    # Caveats
    disclaimers: list[str] = []
    data_gaps: list[str] = []            # fields that were missing / assumed

    # If saved
    saved_assessment_id: Optional[str] = None
    created_at: Optional[str] = None


class DroughtHistoryItem(BaseModel):
    id: str
    owner_id: str
    location: Optional[str] = None
    crop: Optional[str] = None
    growth_stage: Optional[str] = None
    soil_type: Optional[str] = None
    area_value: Optional[float] = None
    area_unit: Optional[str] = None
    created_at: str


class DroughtHistoryResponse(BaseModel):
    total: int
    items: list[DroughtHistoryItem] = []


# ─────────────────────────────────────────────────────────────────────────
# Alerts & Notifications
# ─────────────────────────────────────────────────────────────────────────

class AlertOut(BaseModel):
    id: str
    kind: str
    priority: str
    title: str
    body: Optional[str] = None
    # ``reason`` carries the supporting evidence behind the alert.
    reason: Optional[str] = None
    subject_id: Optional[str] = None
    is_read: bool = False
    # True when the alert was raised from simulated (DEMO) readings.
    is_demo: bool = False
    created_at: str
    updated_at: Optional[str] = None


class AlertListResponse(BaseModel):
    total: int
    unread: int
    items: list[AlertOut] = []


class AlertReadRequest(BaseModel):
    is_read: bool = True


class AlertBulkReadResponse(BaseModel):
    updated: int


# ─────────────────────────────────────────────────────────────────────────
# Unified AI agent  (POST /api/agent/chat, GET /api/agent/context)
# ─────────────────────────────────────────────────────────────────────────

# The agent speaks the same languages as the voice assistant.
SUPPORTED_AGENT_LANGUAGES = SUPPORTED_VOICE_LANGUAGES


class AgentChatRequest(BaseModel):
    """Request body for POST /api/agent/chat.

    ``message``  – the farmer's question (Marathi or English).
    ``language`` – BCP-47 code: "mr" (Marathi) or "en" (English).
    ``farm_id``  – optional; omitted, the caller's newest farm is used.
    ``history``  – optional recent turns (``{"role", "text"}``) so a follow-up
                   such as "what about tomorrow?" keeps its subject.
    """
    message: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="en", pattern=r"^(mr|en)$")
    farm_id: Optional[str] = Field(default=None, max_length=100)
    history: Optional[list[dict[str, Any]]] = Field(default=None, max_length=20)


class AgentChatResponse(BaseModel):
    """Response from POST /api/agent/chat.

    ``answer``      – short, farmer-friendly text (structured sections rendered).
    ``sections``    – the same answer as Situation / Observation /
                      Recommendation / Reason / Warning, so the UI can lay it out
                      without re-parsing the text.
    ``explanation`` – optional natural-language explanation from the assistant,
                      grounded in the values the tools returned.
    ``intent``      – the deterministically routed intent.
    ``tools_used``  – the tools actually called for this question.
    ``context``     – the farm / sensor / weather / ML evidence behind the answer.
    ``conflicts``   – where two sources disagreed (each with its evidence).
    ``uncertainty`` – caveats the farmer should weigh.
    ``missing``     – what was absent, so the answer never hides a data gap.
    ``freshness``   – per-source timestamp of the data used.
    ``llm_used``    – whether the assistant actually generated prose.
    ``sources``     – knowledge-base citations, when the assistant was used.
    ``fallback``    – True when the reply is only the "here is what I can help
                      with" text because nothing about this farm answered the
                      question and the assistant was unavailable.
    """
    answer: str = ""
    sections: dict[str, Any] = {}
    explanation: Optional[str] = None
    language: str = "en"
    intent: str = "unknown"
    intent_label: Optional[str] = None
    tools_used: list[str] = []
    context: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    uncertainty: list[str] = []
    missing: list[str] = []
    freshness: dict[str, Any] = {}
    llm_used: bool = False
    sources: list[dict[str, Any]] = []
    fallback: bool = False
    cached: bool = False


class AgentContextResponse(BaseModel):
    """Response from GET /api/agent/context.

    The complete, structured context of the caller's own farm. Every section
    carries its own source and timestamp, and ``missing`` lists what is absent.
    """
    owner_id: str
    generated_at: str
    farm: Optional[dict[str, Any]] = None
    profile: Optional[dict[str, Any]] = None
    sensors: Optional[dict[str, Any]] = None
    weather: Optional[dict[str, Any]] = None
    ml: dict[str, Any] = {}
    llm_context: Optional[dict[str, Any]] = None
    missing: list[str] = []
    warnings: list[str] = []
