"""Tests for rag_service.smart_answer() — LLM-driven conversational dispatcher.

Covers all the scenarios specified in the upgrade requirements:

1.  Greeting / casual conversation → direct LLM, no RAG.
2.  General agricultural question → direct LLM when confident.
3.  Question where LLM requests retrieval + good RAG result.
4.  Question where LLM requests retrieval + RAG fails (BELOW_THRESHOLD).
5.  Question where LLM requests retrieval + RAG pipeline unavailable.
6.  LLM unavailable + good RAG result (backward-compat fallback).
7.  LLM unavailable + RAG retrieval fails → friendly message, not tech error.
8.  LLM unavailable + both pipeline and RAG unavailable → raises RagUnavailableError.
9.  Internal retrieval error messages never reach the caller.
10. Farm context and ML results are forwarded to the LLM.
11. Language detection: Marathi question gets Marathi fallback message.
12. Sentinel is stripped before the answer is returned.
13. Conversation history is forwarded.
14. Chat endpoint (HTTP) uses smart_answer instead of answer_question.
15. Chat endpoint: 503 only when both LLM and RAG are unavailable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest

from app import rag_service
from app.rag_service import (
    RagUnavailableError,
    _RETRIEVAL_NEEDED_SENTINEL,
    _RETRIEVAL_UNAVAILABLE_MESSAGES,
    smart_answer,
    direct_llm_answer,
    answer_question,
)

# ── Test double helpers ──────────────────────────────────────────────────────

def _llm_result(answer: str, llm_used: bool = True) -> Dict[str, Any]:
    """Minimal return value matching the direct_llm_answer() / answer_question() shape."""
    return {
        "answer": answer,
        "sources": [],
        "retrieval_status": "DIRECT" if llm_used else "LLM_NOT_CONFIGURED",
        "retrieval_message": "",
        "llm_used": llm_used,
        "ml_context_provided": False,
        "warnings": [],
    }


def _rag_ok_result(answer: str) -> Dict[str, Any]:
    return {
        "answer": answer,
        "sources": [{"source": "soil.md", "page": 1, "similarity": 0.82, "snippet": "..."}],
        "retrieval_status": "OK",
        "retrieval_message": "",
        "llm_used": True,
        "ml_context_provided": False,
        "warnings": [],
    }


def _rag_below_threshold_result() -> Dict[str, Any]:
    return {
        "answer": (
            "The knowledge base does not contain sufficient information "
            "to answer this question confidently. Consider adding relevant "
            "agricultural documents to data/raw/ and re-running ingestion."
        ),
        "sources": [],
        "retrieval_status": "BELOW_THRESHOLD",
        "retrieval_message": "Below threshold.",
        "llm_used": False,
        "ml_context_provided": False,
        "warnings": ["Below threshold."],
    }


def _rag_empty_index_result() -> Dict[str, Any]:
    return {
        "answer": "The knowledge base is empty. Please run the ingestion script first.",
        "sources": [],
        "retrieval_status": "EMPTY_INDEX",
        "retrieval_message": "Empty.",
        "llm_used": False,
        "ml_context_provided": False,
        "warnings": [],
    }


# ── 1. Greeting / casual conversation ────────────────────────────────────────

def test_greeting_uses_direct_llm_without_retrieval(monkeypatch):
    """A greeting should be answered by the LLM without triggering RAG."""
    llm_resp = _llm_result("Hello! I'm FarmIQ. How can I help?")
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_resp)

    rag_called = []
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: rag_called.append(1) or _rag_ok_result("ignored"))

    result = smart_answer("Hi")
    assert result["answer"] == "Hello! I'm FarmIQ. How can I help?"
    assert result["llm_used"] is True
    assert len(rag_called) == 0, "answer_question must not be called for a greeting"


def test_casual_chat_no_retrieval(monkeypatch):
    """'How are you?' should be answered without consulting the knowledge base."""
    llm_resp = _llm_result("I'm here and ready to help! What would you like to explore?")
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_resp)

    rag_called = []
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: rag_called.append(1) or _rag_ok_result("ignored"))

    result = smart_answer("How are you?")
    assert "ready" in result["answer"] or "help" in result["answer"]
    assert len(rag_called) == 0


# ── 2. General agricultural question ─────────────────────────────────────────

def test_general_agri_question_answered_by_llm(monkeypatch):
    """A general agricultural question the LLM can answer without documents."""
    llm_resp = _llm_result(
        "Drip irrigation delivers water directly to the root zone, "
        "reducing evaporation by up to 50%."
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_resp)

    rag_called = []
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: rag_called.append(1) or _rag_ok_result("ignored"))

    result = smart_answer("What is drip irrigation?")
    assert "drip" in result["answer"].lower()
    assert len(rag_called) == 0


# ── 3. LLM requests retrieval + good RAG result ───────────────────────────────

def test_llm_requests_retrieval_and_rag_succeeds(monkeypatch):
    """When the LLM emits <<NEEDS_RETRIEVAL>>, RAG is called and its answer is used."""
    sentinel_resp = _llm_result(
        f"ICAR recommends soil tests before applying lime. {_RETRIEVAL_NEEDED_SENTINEL}"
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)

    rag_resp = _rag_ok_result(
        "According to ICAR guidelines, apply 2 t/ha of lime when pH is below 5.5."
    )
    monkeypatch.setattr(rag_service, "answer_question", lambda *a, **kw: rag_resp)

    result = smart_answer("How do I correct soil pH?")
    # The RAG result should be used when retrieval succeeds.
    assert "lime" in result["answer"].lower()
    assert result["retrieval_status"] == "OK"
    assert result["llm_used"] is True
    assert len(result["sources"]) > 0


def test_sentinel_is_stripped_from_answer(monkeypatch):
    """The <<NEEDS_RETRIEVAL>> token must never appear in the returned answer."""
    sentinel_resp = _llm_result(
        f"Some guidance here. {_RETRIEVAL_NEEDED_SENTINEL} More guidance."
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)

    # RAG returns something bad so Phase 1 answer is used.
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: _rag_below_threshold_result())

    result = smart_answer("Which crop should I plant?")
    assert _RETRIEVAL_NEEDED_SENTINEL not in result["answer"]


# ── 4. LLM requests retrieval + RAG fails (BELOW_THRESHOLD) ──────────────────

def test_below_threshold_never_reaches_farmer(monkeypatch):
    """The technical retrieval error message must never be shown to the farmer."""
    sentinel_resp = _llm_result(
        f"For government subsidy details, let me check official sources. "
        f"{_RETRIEVAL_NEEDED_SENTINEL}"
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: _rag_below_threshold_result())

    result = smart_answer("Tell me about PM Kisan scheme")
    # Technical retrieval error must not appear.
    assert "data/raw/" not in result["answer"]
    assert "re-running ingestion" not in result["answer"]
    assert "ingest_documents" not in result["answer"]
    # Phase 1 LLM answer should be used instead.
    assert "subsidy" in result["answer"].lower() or "sources" in result["answer"].lower()


def test_empty_index_message_never_reaches_farmer(monkeypatch):
    """An empty-index message must not be shown to the farmer."""
    sentinel_resp = _llm_result(
        f"For certification details, let me check. {_RETRIEVAL_NEEDED_SENTINEL}"
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: _rag_empty_index_result())

    result = smart_answer("What is organic certification?")
    assert "ingestion script" not in result["answer"]
    assert "knowledge base is empty" not in result["answer"].lower()


# ── 5. LLM requests retrieval + RAG pipeline unavailable ─────────────────────

def test_rag_unavailable_during_phase2_falls_back_to_llm_answer(monkeypatch):
    """When Phase 2 RAG raises RagUnavailableError, Phase 1 answer is used."""
    sentinel_resp = _llm_result(
        f"Based on general knowledge, crop rotation helps soil health. "
        f"{_RETRIEVAL_NEEDED_SENTINEL}"
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            RagUnavailableError("ChromaDB not available")))

    result = smart_answer("Tell me about crop rotation benefits")
    assert "crop rotation" in result["answer"].lower()
    assert _RETRIEVAL_NEEDED_SENTINEL not in result["answer"]
    assert "ChromaDB" not in result["answer"]


# ── 6. LLM unavailable + good RAG result (backward-compat) ───────────────────

def test_llm_unavailable_falls_back_to_rag(monkeypatch):
    """When LLM is not available, good RAG results are returned as-is."""
    llm_unavail = _llm_result("", llm_used=False)
    llm_unavail["retrieval_status"] = "LLM_NOT_CONFIGURED"
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_unavail)

    rag_resp = _rag_ok_result(
        "Wheat grows well in Punjab with rainfall above 500mm annually."
    )
    monkeypatch.setattr(rag_service, "answer_question", lambda *a, **kw: rag_resp)

    result = smart_answer("What are good conditions for wheat?")
    assert "wheat" in result["answer"].lower()
    assert result["retrieval_status"] == "OK"
    assert len(result["sources"]) > 0


# ── 7. LLM unavailable + RAG retrieval fails → friendly message ──────────────

def test_llm_unavailable_rag_below_threshold_returns_friendly_message_en(monkeypatch):
    """English: when both LLM and RAG fail, a friendly English message is returned."""
    llm_unavail = _llm_result("", llm_used=False)
    llm_unavail["retrieval_status"] = "LLM_NOT_CONFIGURED"
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_unavail)
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: _rag_below_threshold_result())

    result = smart_answer("What is the ideal pH for rice?", language="en")
    # Must not expose technical details.
    assert "data/raw/" not in result["answer"]
    assert "re-running ingestion" not in result["answer"]
    assert "ingest_documents" not in result["answer"]
    # Should contain a farmer-friendly message.
    assert "KVK" in result["answer"] or "consult" in result["answer"].lower()


def test_llm_unavailable_rag_below_threshold_returns_friendly_message_mr(monkeypatch):
    """Marathi: friendly fallback message is in Marathi."""
    llm_unavail = _llm_result("", llm_used=False)
    llm_unavail["retrieval_status"] = "LLM_NOT_CONFIGURED"
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_unavail)
    monkeypatch.setattr(rag_service, "answer_question",
                        lambda *a, **kw: _rag_below_threshold_result())

    result = smart_answer("तांदळासाठी pH किती असावा?", language="mr")
    assert "data/raw/" not in result["answer"]
    # The Marathi fallback message contains Devanagari text.
    marathi_msg = _RETRIEVAL_UNAVAILABLE_MESSAGES["mr"]
    assert result["answer"] == marathi_msg


# ── 8. Both LLM and RAG unavailable → raises RagUnavailableError ─────────────

def test_both_llm_and_rag_unavailable_raises(monkeypatch):
    """When both LLM and RAG are unavailable, RagUnavailableError is raised."""
    llm_unavail = _llm_result("", llm_used=False)
    llm_unavail["retrieval_status"] = "LLM_NOT_CONFIGURED"
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_unavail)
    monkeypatch.setattr(
        rag_service, "answer_question",
        lambda *a, **kw: (_ for _ in ()).throw(RagUnavailableError("Pipeline not available"))
    )

    with pytest.raises(RagUnavailableError):
        smart_answer("What is the best crop for my soil?")


# ── 9. Technical messages never reach the caller ─────────────────────────────

def test_ingestion_path_never_appears_in_response_llm_available(monkeypatch):
    """With LLM available: even if RAG fails, no ingestion paths reach the farmer."""
    sentinel_resp = _llm_result(
        f"Some answer. {_RETRIEVAL_NEEDED_SENTINEL}"
    )
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)

    bad_rag = _rag_below_threshold_result()
    monkeypatch.setattr(rag_service, "answer_question", lambda *a, **kw: bad_rag)

    result = smart_answer("Government schemes for farmers")
    for leak in ("data/raw/", "ingest_documents.py", "re-running ingestion",
                 "scripts/", ".env"):
        assert leak not in result["answer"], f"Leaked technical path: {leak!r}"


def test_ingestion_path_never_appears_when_llm_unavailable(monkeypatch):
    """With LLM unavailable: no ingestion paths should reach the farmer either."""
    llm_unavail = _llm_result("", llm_used=False)
    llm_unavail["retrieval_status"] = "LLM_NOT_CONFIGURED"
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: llm_unavail)

    bad_rag = _rag_below_threshold_result()
    monkeypatch.setattr(rag_service, "answer_question", lambda *a, **kw: bad_rag)

    result = smart_answer("Government schemes for farmers", language="en")
    for leak in ("data/raw/", "ingest_documents.py", "re-running ingestion",
                 "Consider adding relevant agricultural documents"):
        assert leak not in result["answer"], f"Leaked: {leak!r}"


# ── 10. Farm context and ML results forwarded ────────────────────────────────

def test_farm_context_forwarded_to_direct_llm_answer(monkeypatch):
    """Farm context must be passed through to direct_llm_answer()."""
    received_ctx = {}

    def _fake_direct(question, *, ml_results=None, language=None, history=None,
                     farm_context=None, **kw):
        received_ctx["farm_context"] = farm_context
        return _llm_result("Advice based on your farm.")

    monkeypatch.setattr(rag_service, "direct_llm_answer", _fake_direct)

    farm = {"location": "Nashik", "soil_type": "black", "current_crop": "onion"}
    smart_answer("Should I water my onions today?", farm_context=farm)
    assert received_ctx["farm_context"] == farm


def test_ml_results_forwarded(monkeypatch):
    """ML results must be passed through to direct_llm_answer()."""
    received = {}

    def _fake_direct(question, *, ml_results=None, **kw):
        received["ml_results"] = ml_results
        return _llm_result("Based on the crop model output...")

    monkeypatch.setattr(rag_service, "direct_llm_answer", _fake_direct)

    ml = {"predicted_crop": "soybean", "confidence": 0.91}
    smart_answer("Explain the crop recommendation", ml_results=ml)
    assert received["ml_results"] == ml


# ── 11. Language detection ────────────────────────────────────────────────────

def test_language_mr_forwarded_to_direct_llm(monkeypatch):
    """Marathi language code is forwarded to direct_llm_answer."""
    received = {}

    def _fake_direct(question, *, language=None, **kw):
        received["language"] = language
        return _llm_result("मी मदत करू शकतो.")

    monkeypatch.setattr(rag_service, "direct_llm_answer", _fake_direct)

    smart_answer("माझ्या शेतात कांदा लावावा का?", language="mr")
    assert received["language"] == "mr"


# ── 12. Conversation history forwarded ───────────────────────────────────────

def test_history_forwarded_to_direct_llm(monkeypatch):
    """Conversation history must be forwarded to direct_llm_answer."""
    received = {}

    def _fake_direct(question, *, history=None, **kw):
        received["history"] = history
        return _llm_result("Using history context...")

    monkeypatch.setattr(rag_service, "direct_llm_answer", _fake_direct)

    history = [
        {"role": "farmer", "text": "My tomato leaves have spots."},
        {"role": "assistant", "text": "That looks like early blight."},
    ]
    smart_answer("Which medicine should I use for it?", history=history)
    assert received["history"] == history


# ── 13. Top-k forwarded to answer_question ───────────────────────────────────

def test_top_k_forwarded_when_retrieval_needed(monkeypatch):
    """top_k parameter must be forwarded to answer_question when retrieval is triggered."""
    received = {}
    sentinel_resp = _llm_result(f"Check docs. {_RETRIEVAL_NEEDED_SENTINEL}")
    monkeypatch.setattr(rag_service, "direct_llm_answer", lambda *a, **kw: sentinel_resp)

    def _fake_rag(question, ml_results=None, *, top_k=None, **kw):
        received["top_k"] = top_k
        return _rag_ok_result("Organic guide says...")

    monkeypatch.setattr(rag_service, "answer_question", _fake_rag)

    smart_answer("Tell me about organic certification", top_k=7)
    assert received["top_k"] == 7


# ── 14 & 15. HTTP endpoint uses smart_answer ─────────────────────────────────

def test_chat_endpoint_uses_smart_answer(app_client, fake_client, monkeypatch):
    """POST /api/chat must call smart_answer, not answer_question directly."""
    called = []
    uid = "chat-user"
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile="+910000000001")
    headers = fake_client.auth_header(uid)

    def _fake_smart(question, *args, **kw):
        called.append(question)
        return _llm_result("Hello! How can I help?")

    monkeypatch.setattr(rag_service, "smart_answer", _fake_smart)

    r = app_client.post("/api/chat", json={"message": "Hello"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["answer"] == "Hello! How can I help?"
    assert called == ["Hello"]


def test_chat_endpoint_503_only_when_both_unavailable(app_client, fake_client, monkeypatch):
    """POST /api/chat returns 503 only when smart_answer raises RagUnavailableError."""
    uid = "chat-user2"
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile="+910000000002")
    headers = fake_client.auth_header(uid)

    def _raise(*a, **kw):
        raise RagUnavailableError("Both LLM and RAG unavailable")

    monkeypatch.setattr(rag_service, "smart_answer", _raise)

    r = app_client.post("/api/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()


def test_chat_endpoint_200_when_llm_answers_greeting(app_client, fake_client, monkeypatch):
    """A greeting gets a 200 response even if RAG pipeline is unconfigured."""
    uid = "chat-user3"
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile="+910000000003")
    headers = fake_client.auth_header(uid)

    def _smart(*a, **kw):
        return _llm_result("Hello! How can I help with your farm today?")

    monkeypatch.setattr(rag_service, "smart_answer", _smart)

    r = app_client.post("/api/chat", json={"message": "Hi"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "Hello" in body["answer"]
    assert body["llm_used"] is True


# ── Existing test_chat.py compatibility ──────────────────────────────────────

def test_existing_chat_test_suite_still_uses_smart_answer_pathway(
    app_client, fake_client, monkeypatch
):
    """Ensure the existing pipeline fake still works through smart_answer.

    The existing test_chat.py tests patch rag_service._pipeline directly. After
    our change, /api/chat calls smart_answer() which calls direct_llm_answer()
    first. When the LLM is not configured on the fake pipeline, smart_answer
    falls through to answer_question() — which is what the existing tests expect.

    This test verifies that a fake pipeline (LLM not configured) causes
    smart_answer to delegate to answer_question as a fallback.
    """
    uid = "compat-user"
    fake_client.seed_profile(uid=uid, email=f"{uid}@example.com", mobile="+910000000009")
    headers = fake_client.auth_header(uid)

    # Simulate a pipeline where LLM is not configured (direct_llm_answer returns
    # llm_used=False), so smart_answer falls back to answer_question.
    answer_q_called = []

    def _direct(*a, **kw):
        return _llm_result("", llm_used=False)

    def _answer_q(question, ml_results=None, *, top_k=None, language=None,
                  history=None, farm_context=None):
        answer_q_called.append(question)
        return _rag_ok_result("Soil pH between 6 and 7 is ideal for most crops.")

    monkeypatch.setattr(rag_service, "direct_llm_answer", _direct)
    monkeypatch.setattr(rag_service, "answer_question", _answer_q)

    r = app_client.post(
        "/api/chat", json={"message": "What soil pH is best?"}, headers=headers
    )
    assert r.status_code == 200
    assert answer_q_called == ["What soil pH is best?"]
    assert "soil" in r.json()["answer"].lower()
