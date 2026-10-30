"""Chat (RAG assistant) endpoint tests.

The RAG pipeline is replaced with a lightweight fake so these tests run without
the heavy RAG dependencies (sentence-transformers, ChromaDB) or a network call.
"""
from __future__ import annotations

import pytest

from app import rag_service
from app.rag_service import RagUnavailableError


# ── Fakes (duck-typed to the RAG module's public interface) ──────────────────
class _Status:
    def __init__(self, name: str):
        self.name = name


class _Item:
    def __init__(self, text: str, source: str, page, similarity: float):
        self.text = text
        self.source = source
        self.page = page
        self.similarity = similarity


class _Result:
    def __init__(self, answer: str, sources=None, status: str = "OK",
                 llm_used: bool = True, warnings=None,
                 farm_context_provided: bool = False):
        self.answer = answer
        self.sources = sources or []
        self.retrieval_status = _Status(status)
        self.retrieval_message = ""
        self.llm_used = llm_used
        self.ml_context_provided = False
        self.farm_context_provided = farm_context_provided
        self.warnings = warnings or []


class _FakeVectorStore:
    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


class _FakeEmbedder:
    model_name = "fake-embed"


class _FakeLLM:
    is_configured = True


class _FakeRetriever:
    def __init__(self, count: int):
        self.vector_store = _FakeVectorStore(count)
        self.embedder = _FakeEmbedder()


class _FakePipeline:
    def __init__(self, result: _Result, count: int = 3):
        self._result = result
        self.retriever = _FakeRetriever(count)
        self.llm_client = _FakeLLM()
        self.calls: list[dict] = []

    def answer(self, question, ml_results=None, *, top_k=None,
               relevance_threshold=None, language=None, history=None,
               farm_context=None):
        self.calls.append({
            "question": question,
            "ml_results": ml_results,
            "top_k": top_k,
            "language": language,
            "history": history,
            "farm_context": farm_context,
        })
        return self._result


@pytest.fixture
def fake_rag(monkeypatch):
    """Install a fake pipeline as the cached RAG pipeline."""
    result = _Result(
        answer="Apply lime based on a soil test.\n\nSources used:\n  [1] soil_health_and_nutrients.md (p. 1)",
        sources=[_Item("Soil pH controls nutrient availability.", "soil_health_and_nutrients.md", 1, 0.81)],
    )
    pipeline = _FakePipeline(result, count=12)
    monkeypatch.setattr(rag_service, "_pipeline", pipeline, raising=False)
    yield pipeline
    monkeypatch.setattr(rag_service, "_pipeline", None, raising=False)


def _auth(fake_client, uid="u1"):
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile=f"+91{uid}0000000")
    return fake_client.auth_header(uid)


def test_chat_requires_auth(app_client):
    r = app_client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 401


def test_chat_answers_via_pipeline(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "How do I fix acidic soil?"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "soil test" in body["answer"]
    assert body["llm_used"] is True
    assert body["retrieval_status"] == "OK"
    assert body["sources"][0]["source"] == "soil_health_and_nutrients.md"
    assert body["sources"][0]["similarity"] == 0.81
    # The question reached the pipeline unchanged.
    assert fake_rag.calls[0]["question"] == "How do I fix acidic soil?"


def test_chat_forwards_ml_results_and_top_k(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    payload = {
        "message": "What suits this crop?",
        "ml_results": {"predicted_crop": "soybean", "yield_prediction": None},
        "top_k": 3,
    }
    r = app_client.post("/api/chat", json=payload, headers=headers)
    assert r.status_code == 200
    assert fake_rag.calls[0]["ml_results"] == {"predicted_crop": "soybean", "yield_prediction": None}
    assert fake_rag.calls[0]["top_k"] == 3


def test_chat_empty_message_rejected(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": ""}, headers=headers)
    assert r.status_code == 422


def test_chat_asks_for_marathi_answer_for_a_marathi_question(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post(
        "/api/chat", json={"message": "माझ्या शेतात कांदा लावावा का?"}, headers=headers
    )
    assert r.status_code == 200
    assert fake_rag.calls[0]["language"] == "mr"


def test_chat_asks_for_english_answer_for_an_english_question(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "How do I fix acidic soil?"}, headers=headers)
    assert r.status_code == 200
    assert fake_rag.calls[0]["language"] == "en"


def test_chat_forwards_recent_history(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    history = [
        {"role": "farmer", "text": "My tomato leaves have brown spots."},
        {"role": "assistant", "text": "That sounds like early blight."},
    ]
    r = app_client.post(
        "/api/chat",
        json={"message": "which medicine should i use for it", "history": history},
        headers=headers,
    )
    assert r.status_code == 200
    assert fake_rag.calls[0]["history"] == history


def test_chat_sends_no_history_for_a_first_question(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "How do I fix acidic soil?"}, headers=headers)
    assert r.status_code == 200
    assert fake_rag.calls[0]["history"] is None


def test_chat_returns_503_when_unavailable(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)

    def _raise():
        raise RagUnavailableError("RAG dependencies are not installed.")

    monkeypatch.setattr(rag_service, "get_pipeline", _raise)
    r = app_client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    assert "RAG dependencies" in r.json()["detail"]


def test_chat_status_reports_readiness(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.get("/api/chat/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["indexed"] is True
    assert body["index_chunks"] == 12
    assert body["llm_configured"] is True


# ── Farm context (requirement #7) ────────────────────────────────────────────
def _seed_farm_and_reading(fake_client, uid="u1", **farm_overrides):
    farm = {
        "id": "farm-1",
        "owner_id": uid,
        "created_at": "2025-02-01T00:00:00+00:00",
        "name": "Ravi's plot",
        "location": "Nashik, Maharashtra",
        "area_value": 2.5,
        "area_unit": "acre",
        "soil_type": "black",
        "current_crop": "onion",
        "irrigation_type": "drip",
        # Must never reach the assistant:
        "latitude": 19.9975,
        "longitude": 73.7898,
    }
    farm.update(farm_overrides)
    reading = {
        "id": "read-1",
        "owner_id": uid,
        "created_at": "2025-06-01T06:30:00+00:00",
        "device_id": "device-secret-token",
        "soil_moisture": 31.5,
        "soil_temperature": 27.0,
        "temperature": 29.4,
        "humidity": 61.0,
        "nitrogen": 42.0,
        "phosphorous": 18.0,
        "potassium": 25.0,
        "ph": 7.4,
        "is_demo": True,
    }
    fake_client.tables["farms"] = [farm]
    fake_client.tables["sensor_readings"] = [reading]
    return farm, reading


def test_chat_forwards_the_farmers_own_context(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    _seed_farm_and_reading(fake_client)

    r = app_client.post("/api/chat", json={"message": "Is my soil ready for onion?"},
                        headers=headers)
    assert r.status_code == 200

    context = fake_rag.calls[0]["farm_context"]
    assert context["name"] == "Ravi's plot"
    assert context["location"] == "Nashik, Maharashtra"
    assert context["soil_type"] == "black"
    assert context["current_crop"] == "onion"
    assert context["irrigation_type"] == "drip"
    assert context["ph"] == 7.4
    assert context["soil_moisture"] == 31.5
    # DEMO readings are labelled so the model never presents them as real.
    assert context["latest_reading_source"] == "DEMO simulated"
    assert context["latest_reading_at"] == "2025-06-01T06:30:00+00:00"


def test_chat_never_shares_private_farm_fields_with_the_ai(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    _seed_farm_and_reading(fake_client)

    r = app_client.post("/api/chat", json={"message": "hello"}, headers=headers)
    assert r.status_code == 200

    context = fake_rag.calls[0]["farm_context"]
    for leaked in ("id", "owner_id", "latitude", "longitude", "device_id",
                   "is_demo", "created_at"):
        assert leaked not in context


def test_chat_sends_no_farm_context_when_the_farmer_has_no_farm(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "hello"}, headers=headers)
    assert r.status_code == 200
    assert fake_rag.calls[0]["farm_context"] is None


def test_chat_reports_whether_farm_context_was_used(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)
    result = _Result(answer="Water every 3 days.", farm_context_provided=True)
    monkeypatch.setattr(rag_service, "_pipeline", _FakePipeline(result), raising=False)
    r = app_client.post("/api/chat", json={"message": "When do I water?"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["farm_context_provided"] is True


# ── ML results are explained, never replaced (requirements #5/#6) ────────────
def test_chat_explains_a_real_ml_prediction_verbatim(app_client, fake_client, fake_rag):
    """The exact ML output the frontend sends must reach the assistant unchanged."""
    headers = _auth(fake_client)
    ml_results = {
        "source": "farmiq_ml_model",
        "domain": "crop",
        "prediction": "soybean",
        "model_source": "pretrained",
        "inputs": {"N": 42, "P": 18, "K": 25, "ph": 6.5, "rainfall": 720},
        "farm": {"name": "Ravi's plot"},
    }
    r = app_client.post(
        "/api/chat", json={"message": "Why soybean?", "ml_results": ml_results}, headers=headers
    )
    assert r.status_code == 200
    assert fake_rag.calls[0]["ml_results"] == ml_results
    assert fake_rag.calls[0]["ml_results"] is ml_results or True  # values, not identity


def test_chat_still_answers_when_the_prediction_has_failed(app_client, fake_client, fake_rag):
    """A failed ML run must not block the assistant (requirements #6/#10)."""
    headers = _auth(fake_client)
    ml_results = {"source": "farmiq_ml_model", "domain": "crop", "error": "model_unavailable"}
    r = app_client.post(
        "/api/chat", json={"message": "What should I do?", "ml_results": ml_results}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["answer"]
    assert fake_rag.calls[0]["ml_results"] == ml_results


# ── Input validation (requirement #11) ───────────────────────────────────────
def test_chat_rejects_a_missing_message(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    assert app_client.post("/api/chat", json={}, headers=headers).status_code == 422


def test_chat_rejects_a_non_object_ml_results(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "hi", "ml_results": ["soybean"]},
                        headers=headers)
    assert r.status_code == 422


def test_chat_rejects_an_out_of_range_top_k(app_client, fake_client, fake_rag):
    headers = _auth(fake_client)
    r = app_client.post("/api/chat", json={"message": "hi", "top_k": 999}, headers=headers)
    assert r.status_code == 422


# ── Safe failure handling (requirements #11/#12) ─────────────────────────────
class _RaisingPipeline(_FakePipeline):
    def __init__(self, exc: Exception):
        super().__init__(_Result(answer=""))
        self._exc = exc

    def answer(self, *args, **kwargs):
        raise self._exc


def test_chat_returns_503_when_answer_generation_times_out(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)
    monkeypatch.setattr(
        rag_service, "_pipeline",
        _RaisingPipeline(TimeoutError("request timed out after 45s")),
        raising=False,
    )
    r = app_client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    assert "timed out" in r.json()["detail"]


def test_chat_returns_503_when_credentials_are_invalid(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)
    secret = "hf_THIS_MUST_NEVER_APPEAR_IN_A_RESPONSE"
    monkeypatch.setattr(
        rag_service, "_pipeline",
        _RaisingPipeline(RuntimeError(f"401 Unauthorized - invalid token {secret}")),
        raising=False,
    )
    r = app_client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    # The error text is redacted: no credential ever leaves the backend.
    assert secret not in r.text
    assert "***" in r.json()["detail"]


def test_chat_returns_503_when_the_model_is_unavailable(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)
    monkeypatch.setattr(
        rag_service, "_pipeline",
        _RaisingPipeline(
            RuntimeError("Answer generation requires a Hugging Face model.")
        ),
        raising=False,
    )
    r = app_client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    assert "Hugging Face" in r.json()["detail"]


def test_chat_status_is_honest_when_the_pipeline_is_unavailable(app_client, fake_client, monkeypatch):
    headers = _auth(fake_client)

    def _raise():
        raise RagUnavailableError("RAG dependencies are not installed.")

    monkeypatch.setattr(rag_service, "get_pipeline", _raise)
    r = app_client.get("/api/chat/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["llm_configured"] is False
    assert "not installed" in body["message"]
