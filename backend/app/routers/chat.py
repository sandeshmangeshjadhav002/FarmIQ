"""AI assistant chat endpoints — LLM-driven conversational assistant.

Exposes the FarmIQ conversational pipeline over HTTP:

* ``POST /api/chat``          — answer a farmer's question using the LLM-driven
  smart dispatcher: the LLM decides whether agricultural document retrieval is
  needed, answers naturally for conversational messages, and uses farm context
  and ML results when available.
* ``GET  /api/chat/status``   — report assistant readiness so the frontend can
  show a friendly state when the LLM or knowledge base is not configured.

Both endpoints require a valid user token (same auth as the rest of the API).
The RAG pipeline is loaded lazily and shared process-wide (see
``app.rag_service``); if both the LLM and the RAG pipeline are unavailable the
chat endpoint returns HTTP 503 with setup instructions rather than crashing.

Answer generation runs on Hugging Face Inference Providers when ``HF_TOKEN`` and
``HF_MODEL_ID`` are configured (backend environment only — never exposed to the
frontend). Without them the RAG project's own provider is used, and if no
provider is configured at all the endpoint still returns the retrieved passages
with a warning instead of failing.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app import rag_service, voice_engine
from app.ai_context import load_farm_context
from app.auth import get_current_user
from app.rag_service import RagUnavailableError
from app.schemas import ChatRequest, ChatResponse, ChatStatusResponse
from app.supabase_client import get_admin_client

logger = logging.getLogger("farmiq.chat")

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user=Depends(get_current_user),
    client=Depends(get_admin_client),
) -> ChatResponse:
    """Answer a farmer's question using the LLM-driven smart dispatcher.

    The LLM decides whether agricultural document retrieval is needed for each
    question. Greetings and general agricultural questions are answered directly.
    Questions that benefit from reference documents trigger retrieval. Failed or
    unhelpful retrievals fall back to the LLM's general knowledge rather than
    exposing technical error messages.
    """
    try:
        result = rag_service.smart_answer(
            payload.message,
            payload.ml_results,
            top_k=payload.top_k,
            # Answer in the language chosen in the UI. When the caller does not
            # send one (older clients, or a bare API call), fall back to the
            # question's own language so a Marathi question is still answered in
            # Marathi even when the app is in English.
            language=payload.language or voice_engine.detect_language(payload.message),
            # Recent turns let follow-up questions ("which medicine for it?")
            # resolve against the subject of the previous turn.
            history=payload.history,
            # The farmer's own farm + latest reading make the answer specific
            # to their land instead of generic advice.
            farm_context=load_farm_context(client, user.id),
        )
    except RagUnavailableError as exc:
        logger.warning("Assistant unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))
    return ChatResponse(**result)


@router.get("/api/chat/status", response_model=ChatStatusResponse)
def chat_status(user=Depends(get_current_user)) -> ChatStatusResponse:
    """Report whether the assistant is available and the index is populated."""
    return ChatStatusResponse(**rag_service.get_status())
