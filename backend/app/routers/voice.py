"""Voice assistant endpoints.

  * POST /api/voice/chat       — transcript → intent → ML model → answer.
  * POST /api/voice/transcribe — recorded audio → text (server-side STT).
  * POST /api/voice/speak      — answer text → MP3 audio (server-side TTS).

Architecture (chat):
  * Validates the request with VoiceChatRequest pydantic schema.
  * Loads the latest sensor reading and the user's farm profile so the engine
    can fill in inputs the farmer did not state (see ml/defaults.py).
  * Calls app.voice_engine.process(), which:
      - Classifies intent deterministically (no LLM).
      - Extracts slots from the transcript.
      - Calls the existing MLAdapter functions directly (no ML logic duplicated).
      - Returns farmer-friendly text in the language of the question (mr/en).
  * Questions the deterministic engine cannot classify at all are handed to
    the RAG assistant (POST /api/voice/chat with intent "knowledge"), so an
    unfamiliar Marathi question is answered rather than rejected. If the
    assistant is unavailable, the engine's guidance text is returned instead.
  * Records the prediction to the predictions table (best-effort).
  * Returns a VoiceChatResponse.

Architecture (transcribe):
  * Chrome/Edge's Web Speech API fails with a "network" error whenever
    Google's speech service is unreachable, and Firefox/Safari do not
    implement it at all. The client records audio with MediaRecorder and posts
    it here; the backend forwards it to an OpenAI-compatible
    /audio/transcriptions provider (Groq Whisper by default).

No new ML logic lives here. The adapter functions in ml/adapter.py are the
single source of truth for model invocation.

Architecture (speak):
  * Windows desktops and stock Android devices frequently have no Marathi or
    Hindi voice installed, so browser/Android speech synthesis stays silent on
    Devanagari text. The client posts the answer here and plays the MP3 that
    app.tts_service synthesises.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app import db, rag_service, tts_service, voice_engine
from app.ai_context import build_farm_context
from app.auth import get_current_user
from app.config import get_settings
from app.errors import AppError
from app.rag_service import RagUnavailableError
from app.schemas import (
    SUPPORTED_VOICE_LANGUAGES,
    SpeechRequest,
    TranscriptionResponse,
    VoiceChatRequest,
    VoiceChatResponse,
)
from app.supabase_client import get_admin_client
from ml.adapter import get_adapter

logger = logging.getLogger("farmiq.voice")
router = APIRouter(prefix="/api/voice", tags=["voice"])

# Whisper accepts up to 25 MB; keep a safety margin below that.
MAX_AUDIO_BYTES = 20 * 1024 * 1024


@router.post("/chat", response_model=VoiceChatResponse)
def voice_chat(
    payload: VoiceChatRequest,
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
) -> VoiceChatResponse:
    """Accept a Marathi or English transcript, route to the correct ML service,
    and return a farmer-friendly structured response."""

    if payload.language not in SUPPORTED_VOICE_LANGUAGES:
        raise AppError(
            400,
            f"Unsupported language '{payload.language}'. "
            f"Supported: {', '.join(SUPPORTED_VOICE_LANGUAGES)}.",
        )

    # Fetch the latest sensor reading so the irrigation engine can use real data.
    latest_sensor: dict | None = None
    try:
        readings, _ = db.list_sensor_readings(client, user.id, limit=1, offset=0)
        latest_sensor = readings[0] if readings else None
    except Exception as exc:  # noqa: BLE001 — sensor fetch is best-effort
        logger.warning("Could not fetch sensor readings for user %s: %s", user.id, exc)

    # Fetch the newest farm so missing inputs can come from the farm profile.
    farm: dict | None = None
    try:
        farms, _ = db.list_farms(client, user.id, limit=1, offset=0)
        farm = farms[0] if farms else None
    except Exception as exc:  # noqa: BLE001 — farm fetch is best-effort
        logger.warning("Could not fetch farms for user %s: %s", user.id, exc)

    # Deterministic intent routing + slot extraction + ML call
    result = voice_engine.process(
        message=payload.message,
        language=payload.language,
        context=payload.context,
        latest_sensor=latest_sensor,
        ml_adapter=get_adapter(),
        farm=farm,
    )

    # The keyword vocabulary and the topic routes could not classify the
    # question — hand it to the RAG assistant instead of replying
    # "I did not understand", so an unfamiliar Marathi question is still
    # answered (in Marathi).
    if result.get("intent") == "unknown":
        result = _answer_with_assistant(
            payload.message,
            result,
            payload.history,
            farm_context=build_farm_context(farm, latest_sensor),
        )

    # Persist prediction when the engine actually called a model (best-effort).
    if result.get("prediction") and not result.get("follow_up"):
        try:
            db.insert_prediction(
                client,
                owner_id=user.id,
                domain=result.get("intent", "unknown"),
                input_data=payload.model_dump(exclude={"message"}),
                output_data=result.get("prediction", {}),
                source="voice",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist voice prediction: %s", exc)

    return VoiceChatResponse(
        response_text=result.get("response_text", ""),
        language=result.get("language", payload.language),
        intent=result.get("intent", "unknown"),
        follow_up=bool(result.get("follow_up")),
        missing_slots=result.get("missing_slots", []),
        prediction=result.get("prediction"),
        speak=True,
    )


def _answer_with_assistant(
    message: str,
    fallback: dict,
    history: list[dict] | None = None,
    farm_context: dict | None = None,
) -> dict:
    """Answer an unrouted question with the RAG assistant.

    *fallback* is the engine's "I did not understand" result. It is returned
    unchanged when the assistant is unavailable, so the endpoint never fails
    because of the knowledge base or the LLM.

    *history* is the optional recent conversation, so a follow-up such as
    "which medicine should I use for it?" can be resolved against the subject
    of the previous turn.

    *farm_context* is the farm and latest reading already loaded by the caller,
    so the assistant can answer about this farmer's own land. It is built with
    :func:`app.ai_context.build_farm_context`, which copies only real database
    values.
    """
    lang = fallback.get("language", "en")
    try:
        answer = rag_service.answer_question(
            message,
            language=lang,
            history=history,
            farm_context=farm_context,
        )
    except RagUnavailableError as exc:
        logger.warning("Assistant unavailable; returning guidance instead: %s", exc)
        return fallback

    text = str(answer.get("answer") or "").strip()
    if not text:
        return fallback

    return {
        **fallback,
        "response_text": text,
        "intent": "knowledge",
        "follow_up": False,
        "missing_slots": [],
        "prediction": None,
    }


async def _transcribe_audio(
    audio: bytes, filename: str, content_type: str, language: str
) -> str:
    """Send recorded audio to the configured OpenAI-compatible STT provider."""
    settings = get_settings()
    if not settings.stt_configured:
        raise AppError(
            503,
            "Speech-to-text is not configured on the server. "
            "Set STT_API_KEY in the backend .env file.",
        )

    url = f"{settings.stt_base_url.rstrip('/')}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=settings.stt_timeout_seconds) as http:
            resp = await http.post(
                url,
                headers={"Authorization": f"Bearer {settings.stt_api_key}"},
                files={"file": (filename, audio, content_type)},
                data={
                    "model": settings.stt_model,
                    "language": language,
                    "response_format": "json",
                    "temperature": "0",
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("Transcription request failed: %s", exc)
        raise AppError(502, f"Could not reach the transcription service: {exc}") from exc

    if resp.status_code >= 400:
        logger.warning(
            "Transcription provider returned %s: %s", resp.status_code, resp.text[:300]
        )
        raise AppError(
            502,
            f"Transcription failed ({resp.status_code}). "
            "Check the STT_API_KEY and STT_MODEL settings.",
        )

    try:
        return str(resp.json().get("text") or "").strip()
    except ValueError as exc:
        raise AppError(502, "Transcription service returned an invalid response.") from exc


@router.post("/transcribe", response_model=TranscriptionResponse)
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form("mr"),
    user=Depends(get_current_user),
) -> TranscriptionResponse:
    """Transcribe an audio recording (webm/mp4/wav/ogg) into text."""
    lang = language if language in SUPPORTED_VOICE_LANGUAGES else "mr"
    audio = await file.read()
    if not audio:
        raise AppError(400, "The uploaded audio file is empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise AppError(
            413,
            f"Audio file too large ({len(audio) // (1024 * 1024)} MB). "
            f"Maximum is {MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
        )

    text = await _transcribe_audio(
        audio,
        file.filename or "recording.webm",
        file.content_type or "audio/webm",
        lang,
    )
    return TranscriptionResponse(
        text=text, language=lang, model=get_settings().stt_model
    )


@router.post(
    "/speak",
    responses={200: {"content": {"audio/mpeg": {}}, "description": "MP3 audio"}},
)
async def voice_speak(
    payload: SpeechRequest,
    user=Depends(get_current_user),
) -> Response:
    """Synthesise answer text into MP3 audio.

    Called by the client only when the device has no voice for the requested
    language — otherwise the local engine is used and no round trip is made.
    """
    audio = await tts_service.synthesize(payload.text, payload.language)
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )
