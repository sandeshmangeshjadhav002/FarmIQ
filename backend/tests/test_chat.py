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
                 llm_used: bool = True, warnings=None):
        self.answer = answer
        self.sources = sources or []
        self.retrieval_status = _Status(status)
        self.retrieval_message = ""
        self.llm_used = llm_used
        self.ml_context_provided = False
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
               relevance_threshold=None, language=None, history=None):
        self.calls.append({
            "question": question,
            "ml_results": ml_results,
            "top_k": top_k,
            "language": language,
            "history": history,
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
