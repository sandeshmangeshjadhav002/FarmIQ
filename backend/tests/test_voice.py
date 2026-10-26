"""Voice assistant endpoint tests.

Uses the same FakeClient fixture as other tests — no real Supabase or ML
model files required. ML adapter calls are mocked with patch() where needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.errors import ModelNotAvailableError
from app.rag_service import RagUnavailableError


# ── helpers ───────────────────────────────────────────────────────────────────

def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def _post(app_client, headers, message, language="mr", context=None):
    return app_client.post(
        "/api/voice/chat",
        json={"message": message, "language": language, "context": context},
        headers=headers,
    )


CROP_SLOT_KEYS = {"N", "P", "K", "temperature", "humidity", "ph", "rainfall"}
FERT_SLOT_KEYS = {"temparature", "humidity", "moisture", "nitrogen", "potassium",
                  "phosphorous", "soil_type", "crop_type"}
IRR_SLOT_KEYS = {"soil_moisture", "soil_temperature", "temperature", "humidity",
                 "crop_days", "crop_type"}
YIELD_SLOT_KEYS = {"state_name", "season", "crop", "crop_year", "area",
                   "annual_rainfall", "fertilizer", "pesticide"}


# ── auth + validation ─────────────────────────────────────────────────────────

def test_voice_chat_requires_auth(app_client):
    r = app_client.post("/api/voice/chat", json={"message": "hello", "language": "en"})
    assert r.status_code == 401


def test_voice_chat_invalid_language_rejected(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "hello", language="fr")
    assert r.status_code == 422  # pydantic pattern validation rejects non-mr/en


# ── navigation / unknown ──────────────────────────────────────────────────────

def test_navigation_help_english(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "what can you do for me?", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "navigation_help"
    assert "crop" in j["response_text"].lower()
    assert j["language"] == "en"
    assert j["follow_up"] is False
    assert j["speak"] is True


def test_navigation_help_marathi(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "मला मदत हवी आहे", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "navigation_help"
    assert j["language"] == "mr"
    # Response must contain Devanagari characters
    assert any(ord(c) > 0x0900 for c in j["response_text"])


def test_unknown_intent_falls_back_to_guidance_when_assistant_unavailable(
    app_client, fake_client
):
    """Off-topic questions keep the guidance text when the assistant is down."""
    h = _auth(fake_client)
    with patch(
        "app.routers.voice.rag_service.answer_question",
        side_effect=RagUnavailableError("RAG dependencies are not installed."),
    ):
        r = _post(app_client, h, "What is the capital of India?", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "unknown"
    assert "did not understand" in j["response_text"].lower()


# ── unrouted questions → RAG assistant (intent "knowledge") ───────────────────

def test_unrouted_marathi_question_is_answered_by_assistant(app_client, fake_client):
    """An unfamiliar Marathi question is answered instead of rejected."""
    h = _auth(fake_client)
    answer = "हवामानाबद्दल माहिती: पुढील काही दिवस पाऊस पडू शकतो."
    with patch(
        "app.routers.voice.rag_service.answer_question",
        return_value={"answer": answer, "sources": [], "llm_used": True},
    ) as mock_answer:
        r = _post(app_client, h, "हवामान कसे आहे?", "mr")

    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "knowledge"
    assert j["response_text"] == answer
    assert j["language"] == "mr"
    assert j["follow_up"] is False
    # The question and the language of the question reach the assistant.
    assert mock_answer.call_args.args[0] == "हवामान कसे आहे?"
    assert mock_answer.call_args.kwargs["language"] == "mr"


def test_marathi_question_is_answered_in_marathi_from_an_english_app(
    app_client, fake_client
):
    """The reply language follows the question, not the app's display language."""
    h = _auth(fake_client)
    r = _post(app_client, h, "मला मदत हवी", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["language"] == "mr"
    assert any(ord(c) > 0x0900 for c in j["response_text"])


def test_follow_up_question_forwards_the_conversation_to_the_assistant(
    app_client, fake_client
):
    """A follow-up such as 'which medicine should I use for it?' keeps its subject."""
    h = _auth(fake_client)
    history = [
        {"role": "farmer", "text": "My tomato leaves have brown spots."},
        {"role": "assistant", "text": "That sounds like early blight."},
    ]
    with patch(
        "app.routers.voice.rag_service.answer_question",
        return_value={"answer": "Choose a product cleared for early blight.", "sources": []},
    ) as mock_answer:
        r = app_client.post(
            "/api/voice/chat",
            json={
                "message": "which medicine should i use for it",
                "language": "en",
                "history": history,
            },
            headers=h,
        )

    assert r.status_code == 200
    assert r.json()["intent"] == "knowledge"
    assert mock_answer.call_args.kwargs["history"] == history


def test_unrouted_english_question_asks_assistant_for_english(app_client, fake_client):
    h = _auth(fake_client)
    with patch(
        "app.routers.voice.rag_service.answer_question",
        return_value={"answer": "General advice.", "sources": [], "llm_used": True},
    ) as mock_answer:
        r = _post(app_client, h, "what is the capital of France?", "en")

    assert r.status_code == 200
    assert r.json()["intent"] == "knowledge"
    assert mock_answer.call_args.kwargs["language"] == "en"


def test_empty_assistant_answer_falls_back_to_guidance(app_client, fake_client):
    h = _auth(fake_client)
    with patch(
        "app.routers.voice.rag_service.answer_question",
        return_value={"answer": "   ", "sources": []},
    ):
        r = _post(app_client, h, "what is the capital of India?", "en")

    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "unknown"
    assert j["prediction"] is None


# ── crop recommendation ───────────────────────────────────────────────────────

def test_crop_missing_slots_marathi_runs_model_with_defaults(app_client, fake_client):
    h = _auth(fake_client)
    # No context and no sensor reading → every input is filled from the raw
    # dataset averages, the model still runs, and the assumed values are
    # listed back to the farmer.
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_crop.return_value = {"prediction": "rice", "details": {}}
        mock_get.return_value = adapter
        r = _post(app_client, h, "माझ्या शेतासाठी योग्य पीक सुचवा", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "crop_recommendation"
    assert j["follow_up"] is False
    assert j["missing_slots"] == []
    assert "rice" in j["response_text"].lower()
    # The model really was called with a fully-populated feature set.
    assert CROP_SLOT_KEYS <= set(adapter.predict_crop.call_args.args[0])
    # Transparency: the assumed-inputs note is present in Marathi.
    assert "गृहीत" in j["response_text"]


def test_crop_missing_slots_english(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_crop.return_value = {"prediction": "maize", "details": {}}
        mock_get.return_value = adapter
        r = _post(app_client, h, "suggest a suitable crop for my field", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "crop_recommendation"
    assert j["follow_up"] is False
    assert CROP_SLOT_KEYS <= set(adapter.predict_crop.call_args.args[0])
    assert "assumed inputs" in j["response_text"].lower()


def test_crop_with_all_slots_calls_model(app_client, fake_client):
    h = _auth(fake_client)
    mock_result = {
        "prediction": "chickpea",
        "details": {"top": [{"crop": "chickpea", "probability": 0.92}]},
    }
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_crop.return_value = mock_result
        mock_get.return_value = adapter
        ctx = {"N": 90, "P": 40, "K": 40, "temperature": 25,
               "humidity": 80, "ph": 6.5, "rainfall": 200}
        r = _post(app_client, h, "crop recommendation", "en", context=ctx)
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "crop_recommendation"
    assert j["follow_up"] is False
    assert "chickpea" in j["response_text"].lower()
    assert j["prediction"] is not None


def test_crop_model_unavailable_returns_error_message(app_client, fake_client):
    h = _auth(fake_client)
    from app import voice_engine

    original_process = voice_engine.process

    def mock_process(message, language, context, latest_sensor, ml_adapter, farm=None):
        mock_adapter = MagicMock()
        mock_adapter.predict_crop.side_effect = Exception("No model file for this domain.")
        return original_process(message, language, context, latest_sensor, mock_adapter, farm)

    with patch.object(voice_engine, "process", side_effect=mock_process):
        ctx = {"N": 90, "P": 40, "K": 40, "temperature": 25,
               "humidity": 80, "ph": 6.5, "rainfall": 200}
        # Use a phrase the intent classifier actually recognises
        r = _post(app_client, h, "crop recommendation for my field", "en", context=ctx)
    assert r.status_code == 200
    j = r.json()
    assert j["follow_up"] is False
    txt = j["response_text"].lower()
    assert any(w in txt for w in ["unavailable", "model", "sorry", "failed", "error"])


# ── fertilizer ────────────────────────────────────────────────────────────────

def test_fertilizer_missing_slots_english(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_fertilizer.return_value = {"prediction": "Urea"}
        mock_get.return_value = adapter
        r = _post(app_client, h, "which fertilizer should I use?", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "fertilizer_recommendation"
    assert j["follow_up"] is False
    assert "urea" in j["response_text"].lower()
    # Categorical inputs are validated against the fitted encoder's classes.
    payload = adapter.predict_fertilizer.call_args.args[0]
    assert FERT_SLOT_KEYS <= set(payload)


def test_fertilizer_missing_slots_marathi(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_fertilizer.return_value = {"prediction": "Urea"}
        mock_get.return_value = adapter
        r = _post(app_client, h, "मला कोणते खत द्यावे?", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "fertilizer_recommendation"
    assert j["follow_up"] is False
    assert j["language"] == "mr"
    assert FERT_SLOT_KEYS <= set(adapter.predict_fertilizer.call_args.args[0])
    assert any(ord(c) > 0x0900 for c in j["response_text"])


def test_fertilizer_with_all_slots_calls_model(app_client, fake_client):
    h = _auth(fake_client)
    mock_result = {"prediction": "Urea", "details": {"soil_type": "Loamy", "crop_type": "Wheat"}}
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_fertilizer.return_value = mock_result
        mock_get.return_value = adapter
        ctx = {"temparature": 26, "humidity": 60, "moisture": 40,
               "nitrogen": 80, "potassium": 20, "phosphorous": 30,
               "soil_type": "Loamy", "crop_type": "Wheat"}
        r = _post(app_client, h, "fertilizer recommendation", "en", context=ctx)
    assert r.status_code == 200
    j = r.json()
    assert j["follow_up"] is False
    assert "urea" in j["response_text"].lower()


# ── irrigation ────────────────────────────────────────────────────────────────

def test_irrigation_with_moisture_calls_model(app_client, fake_client):
    h = _auth(fake_client)
    mock_result = {"prediction": 1, "label": "Irrigate", "source": "baseline",
                   "details": {"rule": "soil_moisture < 30", "threshold": 30}}
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_irrigation.return_value = mock_result
        mock_get.return_value = adapter
        # Provide soil_moisture in context → no follow-up needed
        ctx = {"soil_moisture": 20}
        r = _post(app_client, h, "सिंचन करावे का?", "mr", context=ctx)
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "irrigation"
    assert j["follow_up"] is False
    assert j["prediction"]["prediction"] == 1


def test_irrigation_missing_slots_uses_dataset_defaults(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_irrigation.return_value = {
            "prediction": 1, "label": "Irrigate", "source": "model", "details": {},
        }
        mock_get.return_value = adapter
        # No sensor reading and no stated values → filled from dataset averages.
        r = _post(app_client, h, "when to irrigate?", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "irrigation"
    assert j["follow_up"] is False
    assert IRR_SLOT_KEYS <= set(adapter.predict_irrigation.call_args.args[0])


# ── yield ─────────────────────────────────────────────────────────────────────

def test_yield_missing_slots_english(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_yield.return_value = {"prediction": 2.5, "details": {}}
        mock_get.return_value = adapter
        r = _post(app_client, h, "what is the expected yield for my farm?", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "yield_prediction"
    assert j["follow_up"] is False
    assert YIELD_SLOT_KEYS <= set(adapter.predict_yield.call_args.args[0])
    assert "assumed inputs" in j["response_text"].lower()


def test_yield_with_all_slots_calls_model(app_client, fake_client):
    h = _auth(fake_client)
    mock_result = {"prediction": 2.5, "details": {"unit": "tonnes_per_hectare"}}
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_yield.return_value = mock_result
        mock_get.return_value = adapter
        ctx = {"state_name": "Maharashtra", "season": "Kharif", "crop": "Rice",
               "crop_year": 2023, "area": 1.0, "annual_rainfall": 1000,
               "fertilizer": 50, "pesticide": 5}
        r = _post(app_client, h, "predict yield", "en", context=ctx)
    assert r.status_code == 200
    j = r.json()
    assert j["follow_up"] is False
    assert "2.50" in j["response_text"] or "tonnes" in j["response_text"].lower()


# ── sensor query ──────────────────────────────────────────────────────────────

def test_sensor_no_data_returns_friendly_message(app_client, fake_client):
    h = _auth(fake_client)
    # Marathi sensor-specific phrase that won't collide with irrigation keywords
    r = _post(app_client, h, "sensor data दाखवा", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "sensor_query"
    assert j["prediction"] is None


def test_sensor_english_no_reading(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "show me the sensor data", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "sensor_query"


def test_sensor_with_real_reading_shows_values(app_client, fake_client):
    h = _auth(fake_client)
    reading = {"id": "r1", "owner_id": "u1", "farm_id": None,
               "device_id": "dev1", "soil_moisture": 55.0, "temperature": 28.0,
               "humidity": 65.0, "soil_moisture_raw": None, "soil_temperature": None,
               "created_at": "2026-10-24T10:00:00+00:00"}
    fake_client.tables["sensor_readings"] = [reading]
    r = _post(app_client, h, "माती ओलावा किती आहे?", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "sensor_query"
    # Response should mention the actual moisture value
    assert "55" in j["response_text"]


# ── language switching ────────────────────────────────────────────────────────

def test_language_mr_response_contains_devanagari(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "मला मदत हवी", "mr")
    assert r.json()["language"] == "mr"
    assert any(ord(c) > 0x0900 for c in r.json()["response_text"])


def test_language_en_response_is_english(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "help me", "en")
    assert r.json()["language"] == "en"
    txt = r.json()["response_text"]
    # English response should not be entirely non-ASCII
    assert any(c.isascii() and c.isalpha() for c in txt)


# ── speak flag always true ────────────────────────────────────────────────────

def test_response_always_includes_speak_true(app_client, fake_client):
    h = _auth(fake_client)
    r = _post(app_client, h, "help", "en")
    assert r.json()["speak"] is True


# ── topic routing (no dedicated model → closest ML model) ─────────────────────

def test_soil_question_routed_to_fertilizer_model(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_fertilizer.return_value = {"prediction": "Urea"}
        mock_get.return_value = adapter
        r = _post(app_client, h, "tell me about soil health in my field", "en")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "fertilizer_recommendation"
    assert adapter.predict_fertilizer.called
    assert "closest" in j["response_text"].lower()


def test_pest_question_routed_to_crop_model(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        adapter = MagicMock()
        adapter.predict_crop.return_value = {"prediction": "rice", "details": {}}
        mock_get.return_value = adapter
        r = _post(app_client, h, "माझ्या पिकाला कीटक पडले आहेत", "mr")
    assert r.status_code == 200
    j = r.json()
    assert j["intent"] == "crop_recommendation"
    assert adapter.predict_crop.called
    # The farmer is told which analysis was used instead of a dedicated model.
    assert "मॉडेल" in j["response_text"]


def test_off_topic_question_is_not_routed_to_a_model(app_client, fake_client):
    """Off-topic questions never run an ML model — they go to the assistant."""
    h = _auth(fake_client)
    with patch("app.routers.voice.get_adapter") as mock_get:
        with patch(
            "app.routers.voice.rag_service.answer_question",
            return_value={"answer": "Not a farming topic.", "sources": []},
        ):
            r = _post(app_client, h, "who is the president of France?", "en")

    assert r.status_code == 200
    assert r.json()["intent"] == "knowledge"
    mock_get.return_value.predict_crop.assert_not_called()
    mock_get.return_value.predict_fertilizer.assert_not_called()
    mock_get.return_value.predict_yield.assert_not_called()
    mock_get.return_value.predict_irrigation.assert_not_called()


# ── server-side speech-to-text (POST /api/voice/transcribe) ───────────────────

class _FakeSttResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"text": "माझ्या शेतासाठी योग्य पीक सुचवा"}


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so no real provider call is made."""

    last_call: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeAsyncClient.last_call = {"url": url, **kwargs}
        return _FakeSttResponse()


def _audio_post(app_client, headers, language="mr"):
    return app_client.post(
        "/api/voice/transcribe",
        files={"file": ("speech.webm", b"\x1aE\xdf\xa3fake-opus-audio", "audio/webm")},
        data={"language": language},
        headers=headers,
    )


def test_transcribe_requires_auth(app_client):
    r = _audio_post(app_client, headers={})
    assert r.status_code == 401


def test_transcribe_returns_503_when_not_configured(app_client, fake_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("STT_API_KEY", "")
    get_settings.cache_clear()
    h = _auth(fake_client)
    r = _audio_post(app_client, h)
    assert r.status_code == 503
    assert "STT_API_KEY" in r.json()["detail"]


def test_transcribe_rejects_empty_audio(app_client, fake_client):
    h = _auth(fake_client)
    r = app_client.post(
        "/api/voice/transcribe",
        files={"file": ("speech.webm", b"", "audio/webm")},
        data={"language": "mr"},
        headers=h,
    )
    assert r.status_code == 400


def test_transcribe_forwards_audio_to_whisper(app_client, fake_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("STT_API_KEY", "test-key")
    get_settings.cache_clear()
    h = _auth(fake_client)

    with patch("app.routers.voice.httpx.AsyncClient", _FakeAsyncClient):
        r = _audio_post(app_client, h)

    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "माझ्या शेतासाठी योग्य पीक सुचवा"
    assert body["language"] == "mr"
    assert body["model"] == "whisper-large-v3"

    call = _FakeAsyncClient.last_call
    assert call["url"].endswith("/audio/transcriptions")
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["data"]["model"] == "whisper-large-v3"
    assert call["data"]["language"] == "mr"
    filename, audio, content_type = call["files"]["file"]
    assert filename == "speech.webm"
    assert content_type == "audio/webm"
    assert audio


def test_transcribe_reports_provider_error(app_client, fake_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("STT_API_KEY", "test-key")
    get_settings.cache_clear()
    h = _auth(fake_client)

    class _Failing(_FakeAsyncClient):
        async def post(self, url, **kwargs):
            resp = _FakeSttResponse()
            resp.status_code = 401
            return resp

    with patch("app.routers.voice.httpx.AsyncClient", _Failing):
        r = _audio_post(app_client, h)

    assert r.status_code == 502
    assert "STT_API_KEY" in r.json()["detail"]


# ── server-side text-to-speech (POST /api/voice/speak) ───────────────────────

class _FakeCommunicate:
    """Stands in for edge_tts.Communicate so no network call is made."""

    calls: list = []

    def __init__(self, text, voice, **kwargs):
        _FakeCommunicate.calls.append({"text": text, "voice": voice})

    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0}
        yield {"type": "audio", "data": b"ID3-fake-mp3"}


class _FakeEdgeTts:
    Communicate = _FakeCommunicate


def _speak_post(app_client, headers, text="नमस्कार", language="mr"):
    return app_client.post(
        "/api/voice/speak", json={"text": text, "language": language}, headers=headers
    )


def test_speak_requires_auth(app_client):
    assert _speak_post(app_client, headers={}).status_code == 401


def test_speak_rejects_empty_text(app_client, fake_client):
    h = _auth(fake_client)
    assert _speak_post(app_client, h, text="").status_code == 422


def test_speak_rejects_unsupported_language(app_client, fake_client):
    h = _auth(fake_client)
    assert _speak_post(app_client, h, language="fr").status_code == 422


def test_speak_returns_marathi_mp3(app_client, fake_client):
    h = _auth(fake_client)
    _FakeCommunicate.calls.clear()
    with patch("app.tts_service.edge_tts", _FakeEdgeTts):
        r = _speak_post(app_client, h, "नमस्कार, मी तुमचा सहाय्यक आहे.", "mr")

    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3-fake-mp3"
    assert _FakeCommunicate.calls[-1]["voice"] == "mr-IN-AarohiNeural"
    assert _FakeCommunicate.calls[-1]["text"] == "नमस्कार, मी तुमचा सहाय्यक आहे."


def test_speak_uses_english_voice_for_english_text(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.tts_service.edge_tts", _FakeEdgeTts):
        r = _speak_post(app_client, h, "Hello farmer", "en")

    assert r.status_code == 200
    assert _FakeCommunicate.calls[-1]["voice"] == "en-IN-NeerjaNeural"


def test_speak_returns_503_when_edge_tts_missing(app_client, fake_client):
    h = _auth(fake_client)
    with patch("app.tts_service.edge_tts", None):
        r = _speak_post(app_client, h)

    assert r.status_code == 503
    assert "requirements.txt" in r.json()["detail"]


def test_speak_reports_provider_failure(app_client, fake_client):
    h = _auth(fake_client)

    class _BrokenCommunicate(_FakeCommunicate):
        async def stream(self):
            raise RuntimeError("websocket closed")
            yield  # pragma: no cover — unreachable, makes this a generator

    class _BrokenEdgeTts:
        Communicate = _BrokenCommunicate

    with patch("app.tts_service.edge_tts", _BrokenEdgeTts):
        r = _speak_post(app_client, h)

    assert r.status_code == 502
    assert "speech synthesis" in r.json()["detail"].lower()


def test_speak_returns_503_when_disabled(app_client, fake_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("TTS_ENABLED", "false")
    get_settings.cache_clear()
    h = _auth(fake_client)
    r = _speak_post(app_client, h)
    assert r.status_code == 503
    assert "not enabled" in r.json()["detail"]
