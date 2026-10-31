"""Bridge between the FastAPI backend and the standalone FarmIQ-RAG pipeline.

The RAG project (``FarmIQ-rag/FarmIQ-RAG``) is an independent Python library
with its own, comparatively heavy dependencies (``sentence-transformers``,
``chromadb``, ``langchain-text-splitters``). To keep the core API importable
without them, the RAG package is imported **lazily on first use**:

* Importing this module has no side effects and no heavy imports.
* The pipeline is a process-wide singleton — the embedding model loads once and
  the ChromaDB connection is reused across requests.
* If the RAG project, its dependencies, or its vector index are unavailable, a
  :class:`RagUnavailableError` is raised with actionable setup instructions so
  the endpoint can return HTTP 503 instead of crashing the application.

The RAG project keeps its own configuration (``FarmIQ-RAG/.env``) for retrieval
parameters. Answer generation, however, is configured **once** through the
backend environment: when ``HF_TOKEN`` and ``HF_MODEL_ID`` are set, this bridge
overrides the RAG project's LLM block so the official
``huggingface_hub.InferenceClient`` (Hugging Face Inference Providers) is used.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import Settings, get_settings

logger = logging.getLogger("farmiq.rag")


class RagUnavailableError(RuntimeError):
    """Raised when the RAG pipeline cannot be loaded or used in this environment.

    The message is safe to show to an operator (it never contains secrets) and
    explains how to enable the assistant.
    """


class RagTimeoutError(RagUnavailableError):
    """Raised when an answer was abandoned because it ran over its budget.

    A subclass of :class:`RagUnavailableError` so callers that already treat an
    unavailable assistant gracefully keep working; callers that want to tell
    "too slow" apart from "not installed" can catch this first.
    """


class LLMTimeoutError(TimeoutError):
    """A single LLM call did not finish inside the budget its caller allowed."""


# ── Wall-clock budgeting for LLM calls ────────────────────────────────────
# One assistant request may make several LLM calls (tool plan, direct answer,
# RAG answer). Each call has its own HTTP timeout, but their *sum* can exceed
# the web/app client's 90s deadline (CHAT_TIMEOUT_MS) when a provider is slow,
# so the farmer sees a network timeout instead of an answer. These helpers let
# a caller impose a hard wall-clock cap per call: once it is spent the request
# stops waiting and the assistant returns its deterministic, structured answer.
#
# The worker thread cannot be interrupted, so a genuinely stuck provider keeps
# running until its own HTTP timeout expires — but the *request* returns on
# time, which is what the client deadline cares about.
_budget_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="farmiq-llm")


def _call_bounded(fn: Callable[[], Any], timeout: Optional[float]) -> Any:
    """Run ``fn()`` and stop waiting after ``timeout`` seconds.

    ``None`` runs the call unbounded (previous behaviour). A non-positive
    ``timeout`` means the budget is already spent, so the call is skipped and
    :class:`LLMTimeoutError` is raised without starting any work. Any exception
    raised by ``fn`` itself propagates unchanged.
    """
    if timeout is None:
        return fn()
    if timeout <= 0:
        raise LLMTimeoutError("The LLM budget for this request is exhausted.")
    future = _budget_pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    except _FutureTimeout as exc:
        # ``concurrent.futures.TimeoutError`` is an alias of the builtin in
        # modern Python, so a callable that raised its *own* TimeoutError would
        # land here too. Only a future that is still running means the budget
        # elapsed; a finished future means the provider really failed.
        if future.done():
            raise
        future.cancel()
        raise LLMTimeoutError(
            f"LLM call exceeded its {timeout:.1f}s budget."
        ) from exc


def remaining_budget(deadline: Optional[float]) -> Optional[float]:
    """Seconds left before *deadline* (a ``time.monotonic()`` value).

    Returns ``None`` when no deadline is set, and ``0.0`` once it has passed so
    callers can skip work rather than start a call they cannot finish.
    """
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


_lock = threading.Lock()
_pipeline: Any = None  # RAGPipeline | None

# Third-party clients occasionally echo the credential they rejected straight
# into the error text. Requirement: secrets never reach the frontend or the
# logs, so anything that looks like a token is scrubbed before a message is
# raised or logged.
_SECRET_PATTERNS = (
    re.compile(r"\bhf_[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{6,}"),
)


def _redact_secrets(text: str) -> str:
    """Return *text* with any credential-looking substring replaced."""
    redacted = str(text)
    token = (get_settings().hf_token or "").strip()
    if token:
        redacted = redacted.replace(token, "***")
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("***", redacted)
    return redacted


def _install_hint() -> str:
    return (
        "The FarmIQ assistant (RAG) is not available. To enable it:\n"
        "  1. Install the RAG dependencies into the backend environment:\n"
        "       .venv\\Scripts\\python -m pip install -r "
        "..\\FarmIQ-rag\\FarmIQ-RAG\\requirements.txt\n"
        "  2. Add agricultural documents to FarmIQ-rag/FarmIQ-RAG/data/raw/\n"
        "  3. Build the index:\n"
        "       cd ..\\FarmIQ-rag\\FarmIQ-RAG && python scripts/ingest_documents.py\n"
        "  4. (Optional) Set LLM_API_KEY and LLM_MODEL in "
        "FarmIQ-rag/FarmIQ-RAG/.env to generate answers.\n"
    )


def _resolve_project_dir() -> Path:
    project_dir = get_settings().rag_project_dir
    if not project_dir.exists() or not (project_dir / "src" / "rag_pipeline.py").exists():
        raise RagUnavailableError(
            f"FarmIQ-RAG project not found at '{project_dir}'. "
            "Set FARMIQ_RAG_PATH to the FarmIQ-RAG project directory.\n"
            + _install_hint()
        )
    return project_dir


def _import_rag_pipeline() -> Any:
    """Import ``src.rag_pipeline`` from the RAG project, or raise a clear error."""
    project_dir = _resolve_project_dir()
    project_str = str(project_dir)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    try:
        import src.rag_pipeline as rag_pipeline  # type: ignore
    except ImportError as exc:
        raise RagUnavailableError(
            f"Failed to import the FarmIQ-RAG package ({exc}).\n" + _install_hint()
        ) from exc

    # Guard against an unrelated top-level ``src`` package shadowing the RAG one.
    module_file = Path(getattr(rag_pipeline, "__file__", "")).resolve()
    if project_dir.resolve() not in module_file.parents:
        raise RagUnavailableError(
            f"Imported 'src.rag_pipeline' from an unexpected location: {module_file}. "
            "Another 'src' package is shadowing the FarmIQ-RAG package.\n" + _install_hint()
        )
    return rag_pipeline


def _apply_hf_settings(rag_settings: Any, settings: Settings) -> Any:
    """Return the RAG project's settings with the backend's HF config applied.

    The RAG project reads its own ``.env``, but a deployment should only have to
    set ``HF_TOKEN`` / ``HF_MODEL_ID`` once — in the backend environment. When
    the backend is configured for Hugging Face, its values override the RAG
    project's LLM block so :func:`build_llm_client` selects
    :class:`~src.llm_client.HuggingFaceClient`.

    When the backend has no HF credentials the RAG settings are returned
    unchanged, so an existing Groq/OpenAI-compatible setup keeps working.
    """
    if not settings.hf_configured:
        return rag_settings

    token = settings.hf_token.strip()
    model_id = settings.hf_model_id.strip()
    return replace(
        rag_settings,
        llm_provider="huggingface",
        # LLM_API_KEY / LLM_MODEL are the RAG project's aliases for the token
        # and model; HF_TOKEN / HF_MODEL_ID are set too, so both surfaces agree.
        llm_api_key=token,
        llm_model=model_id,
        hf_token=token,
        hf_model_id=model_id,
        hf_provider=(settings.hf_provider or "").strip() or None,
        llm_request_timeout=float(settings.hf_timeout_seconds),
    )


def get_pipeline() -> Any:
    """Return the process-wide :class:`RAGPipeline`, building it on first use."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _lock:
        if _pipeline is None:
            rag_pipeline = _import_rag_pipeline()
            try:
                settings = _apply_hf_settings(rag_pipeline.get_settings(), get_settings())
                _pipeline = rag_pipeline.build_rag_pipeline(settings=settings)
            except RagUnavailableError:
                raise
            except Exception as exc:  # missing deps surface here
                raise RagUnavailableError(
                    f"Failed to initialise the RAG pipeline ({type(exc).__name__}: {exc}).\n"
                    + _install_hint()
                ) from exc
            logger.info("RAG pipeline initialised.")
    return _pipeline


def reset_pipeline() -> None:
    """Drop the cached pipeline (used by tests and after re-ingestion)."""
    global _pipeline
    with _lock:
        _pipeline = None


def _serialize_result(result: Any) -> Dict[str, Any]:
    """Convert an :class:`AnswerResult` into a JSON-serialisable dict."""
    sources: List[Dict[str, Any]] = []
    for item in getattr(result, "sources", []) or []:
        snippet = str(getattr(item, "text", ""))[:600].strip()
        sources.append(
            {
                "source": str(getattr(item, "source", "unknown")),
                "page": getattr(item, "page", None),
                "similarity": round(float(getattr(item, "similarity", 0.0)), 4),
                "snippet": snippet,
            }
        )

    status = getattr(result, "retrieval_status", None)
    status_name = getattr(status, "name", str(status or "OK"))

    return {
        "answer": str(getattr(result, "answer", "") or ""),
        "sources": sources,
        "retrieval_status": status_name,
        "retrieval_message": str(getattr(result, "retrieval_message", "") or ""),
        "llm_used": bool(getattr(result, "llm_used", False)),
        "ml_context_provided": bool(getattr(result, "ml_context_provided", False)),
        "farm_context_provided": bool(getattr(result, "farm_context_provided", False)),
        "warnings": list(getattr(result, "warnings", []) or []),
    }


def answer_question(
    question: str,
    ml_results: Optional[Dict[str, Any]] = None,
    *,
    top_k: Optional[int] = None,
    relevance_threshold: Optional[float] = None,
    language: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    farm_context: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Answer *question* through the RAG pipeline and return a JSON-ready dict.

    ``language`` is an optional answer-language hint ("mr" or "en"); when it is
    omitted the assistant follows the language of the question itself.

    ``history`` is an optional list of recent conversation turns
    (``{"role": "farmer"|"assistant", "text": "..."}``) so that a follow-up
    question such as "which medicine should I use for it?" can be resolved
    against the previous subject. Omit it for a single, self-contained question.

    ``farm_context`` is an optional dictionary of facts the caller already
    knows about the farmer's own farm (name, location, area, soil type, current
    crop, irrigation type, latest real sensor reading). Only the values supplied
    are passed to the model, as background — never as predictions, and never
    filled in when they are missing.

    ``timeout`` is an optional wall-clock cap in seconds. When the retrieval and
    generation together exceed it the call is abandoned and
    :class:`RagTimeoutError` is raised, so the assistant can answer from its
    deterministic path instead of leaving the client waiting.

    Raises :class:`RagUnavailableError` when the assistant is not available.
    """
    pipeline = get_pipeline()
    try:
        result = _call_bounded(
            lambda: pipeline.answer(
                question,
                ml_results,
                top_k=top_k,
                relevance_threshold=relevance_threshold,
                language=language,
                history=history,
                farm_context=farm_context,
            ),
            timeout,
        )
    except RagUnavailableError:
        raise
    except LLMTimeoutError as exc:
        logger.warning("RAG answer abandoned: %s", exc)
        raise RagTimeoutError("The assistant took too long to answer.") from exc
    except Exception as exc:
        detail = _redact_secrets(f"{type(exc).__name__}: {exc}")
        logger.error("RAG answer generation failed: %s", detail)
        raise RagUnavailableError(
            f"The assistant failed to answer ({detail})."
        ) from exc
    return _serialize_result(result)


def probe_llm_model(model_id: str = "", *, provider: str = "") -> Dict[str, Any]:
    """Check whether *model_id* is live on a Hugging Face Inference Provider.

    Unlike :func:`check_model_availability`, this does not need the RAG pipeline
    (or its heavy dependencies, or a built vector index) — it loads the RAG
    project's availability check directly. It is what
    ``scripts/verify_llm_model.py`` calls before answer generation is enabled.

    Never raises and never includes the token in its result.
    """
    settings = get_settings()
    model_id = (model_id or settings.hf_model_id).strip()
    provider = (provider or settings.hf_provider or "").strip()

    result: Dict[str, Any] = {
        "model": model_id,
        "available": False,
        "provider": provider or "auto",
        "providers": [],
        "message": "",
    }
    if not model_id:
        result["message"] = "No Hugging Face model id is configured."
        return result

    try:
        project_dir = _resolve_project_dir()
    except RagUnavailableError as exc:
        result["message"] = str(exc)
        return result

    project_str = str(project_dir)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    try:
        from src import llm_client as rag_llm_client  # type: ignore
    except ImportError as exc:
        result["message"] = (
            f"The FarmIQ-RAG project could not be imported ({exc}). Install its "
            "dependencies (see .env.example) and retry."
        )
        return result

    # Guard against an unrelated top-level ``src`` package shadowing the RAG one.
    module_file = Path(getattr(rag_llm_client, "__file__", "")).resolve()
    if project_dir.resolve() not in module_file.parents:
        result["message"] = (
            f"Imported 'src.llm_client' from an unexpected location: {module_file}."
        )
        return result

    return rag_llm_client.check_model_availability(
        model_id,
        token=settings.hf_token.strip() or None,
        provider=provider or None,
        timeout=float(settings.hf_timeout_seconds),
    )


def check_model_availability() -> Dict[str, Any]:
    """Report whether the configured LLM model is served by a live provider.

    Hugging Face Inference Providers only: the check asks the Hub which
    providers currently serve ``HF_MODEL_ID``. For any other provider — or when
    the assistant is unavailable — a small ``{"available": False, ...}`` dict is
    returned instead of raising, so a caller (a deploy script, a health probe)
    never has to guard against an exception.

    Never raises. Never includes the token in its output.
    """
    try:
        pipeline = get_pipeline()
    except RagUnavailableError as exc:
        return {
            "available": False,
            "model": get_settings().hf_model_id.strip(),
            "provider": "",
            "providers": [],
            "message": str(exc),
        }

    checker = getattr(pipeline.llm_client, "check_availability", None)
    if not callable(checker):
        return {
            "available": bool(getattr(pipeline.llm_client, "is_configured", False)),
            "model": str(getattr(pipeline.llm_client, "model_name", "") or ""),
            "provider": "",
            "providers": [],
            "message": (
                "Availability checks are only implemented for the Hugging Face "
                "provider; the configured provider reports itself as "
                + ("configured." if getattr(pipeline.llm_client, "is_configured", False) else "unconfigured.")
            ),
        }
    return dict(checker())


def get_status() -> Dict[str, Any]:
    """Report assistant availability without raising.

    Returns a dict with ``available`` (pipeline could be loaded) and
    ``indexed`` (the vector index contains at least one chunk), plus the
    embedding model name, the number of indexed chunks and the configured
    answer-generation provider/model. On failure, ``available`` is ``False``
    and ``message`` explains why.
    """
    try:
        pipeline = get_pipeline()
    except RagUnavailableError as exc:
        return {
            "available": False,
            "indexed": False,
            "index_chunks": 0,
            "llm_configured": False,
            "llm_provider": None,
            "llm_model": None,
            "embedding_model": None,
            "message": str(exc),
        }

    chunks = 0
    try:
        chunks = int(pipeline.retriever.vector_store.count())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read the vector index count: %s", exc)

    llm_client = getattr(pipeline, "llm_client", None)
    provider = None
    try:
        provider = str(pipeline.settings.llm_provider or "") or None
    except Exception:  # pragma: no cover - defensive
        provider = None

    return {
        "available": True,
        "indexed": chunks > 0,
        "index_chunks": chunks,
        "llm_configured": bool(getattr(llm_client, "is_configured", False)),
        "llm_provider": provider,
        "llm_model": getattr(llm_client, "model_name", None) or None,
        "embedding_model": getattr(pipeline.retriever.embedder, "model_name", None),
        "message": "" if chunks > 0 else "The knowledge base is empty; run ingestion.",
    }


# ---------------------------------------------------------------------------
# Direct LLM answer (no retrieval required)
# ---------------------------------------------------------------------------
# This entry point calls the LLM without going through the vector store.
# It is used when:
#   * The question is conversational (greetings, casual chat).
#   * The question can be answered from the LLM's general agricultural
#     knowledge plus the farm context the agent already gathered.
#   * The knowledge base returned BELOW_THRESHOLD or is empty, but the LLM
#     can still give a useful answer using its own knowledge.
#
# Farm-specific facts (sensor readings, ML predictions, weather) are passed
# as structured context so the LLM's reply is personalised without retrieving
# any documents.

_DIRECT_SYSTEM_PROMPT = """You are FarmIQ, a friendly and knowledgeable agricultural assistant \
designed to help farmers in India. You support both English and Marathi.

Your job is to:
1. Respond naturally to greetings and casual conversation.
2. Answer general agricultural questions using your knowledge.
3. Give personalised farm advice when farm data is provided.
4. Ask for missing information when it is essential for a specific recommendation.
5. Redirect unrelated questions politely without being repetitive.

Rules:
- Never invent sensor readings, ML predictions, weather observations, or \
government scheme details.
- When farm data is provided, use it. When it is absent, say what is missing \
and offer general guidance.
- Label ML predictions as model output, not verified facts.
- Label sensor readings as sensor readings, not measurements you made.
- Keep answers concise and farmer-friendly. Avoid jargon.
- Answer in the language the farmer used (Marathi in Devanagari if they wrote in Marathi).
- For high-stakes decisions (pesticide doses, chemical applications, large \
capital expenditure), recommend consulting a local agricultural officer or KVK.
- Do not expose internal system details, file paths, or error messages.
"""


def direct_llm_answer(
    question: str,
    *,
    ml_results: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    farm_context: Optional[Dict[str, Any]] = None,
    tool_results_summary: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Call the LLM directly without knowledge-base retrieval.

    Suitable for greetings, general agricultural questions, and farm-specific
    questions where the agent's tool data is sufficient context.

    ``timeout`` is an optional wall-clock cap in seconds; when the provider does
    not answer in time the result carries ``retrieval_status="LLM_TIMEOUT"`` and
    no text, so the caller can fall back instead of holding the client open.

    Returns a dict with the same keys as ``answer_question`` so callers can
    treat both paths uniformly.
    """
    try:
        pipeline = get_pipeline()
    except RagUnavailableError:
        # The RAG stack is not initialised, but the LLM client may be
        # accessible directly via the RAG project's settings.
        pass
    else:
        # Use the pipeline's existing LLM client — no new credentials needed.
        llm = pipeline.llm_client
        if not llm.is_configured:
            return {
                "answer": "",
                "sources": [],
                "retrieval_status": "LLM_NOT_CONFIGURED",
                "retrieval_message": "LLM provider is not configured.",
                "llm_used": False,
                "ml_context_provided": bool(ml_results),
                "warnings": ["LLM not configured — no answer generated."],
            }

        # Build a compact user prompt from available context.
        sections: List[str] = []

        if farm_context:
            facts = "\n".join(
                f"  {k}: {v}" for k, v in farm_context.items()
                if v is not None and str(v).strip()
            )
            if facts:
                sections.append(
                    "Farm data on file (real values, not invented):\n" + facts
                )

        if ml_results:
            ml_lines = "\n".join(
                f"  {k}: {v}" for k, v in ml_results.items()
                if v is not None
            )
            if ml_lines:
                sections.append(
                    "FarmIQ ML model outputs (model predictions, not verified facts):\n"
                    + ml_lines
                )

        if tool_results_summary:
            sections.append(
                "FarmIQ tool data (from the farmer's actual account):\n"
                + tool_results_summary
            )

        # Recent conversation history for follow-up resolution.
        if history:
            turns: List[str] = []
            for item in (history or [])[-6:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").lower()
                text = str(item.get("text") or item.get("content") or "").strip()
                if not text:
                    continue
                label = "Farmer" if role in {"farmer", "user"} else "Assistant"
                turns.append(f"{label}: {text[:600]}")
            if turns:
                sections.append(
                    "Recent conversation (for context only — do not repeat earlier answers):\n"
                    + "\n".join(turns)
                )

        lang_label = {
            "mr": "Marathi (Devanagari script, मराठी)",
            "en": "English",
        }.get((language or "").strip().lower())
        if lang_label:
            sections.append(f"Answer in {lang_label}.")

        sections.append(f"Farmer's question:\n{question}\n\nAnswer:")
        prompt = "\n\n".join(sections)

        settings = pipeline.settings
        try:
            answer_text = _call_bounded(
                lambda: llm.generate(
                    prompt,
                    system=_DIRECT_SYSTEM_PROMPT,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                ),
                timeout,
            )
        except LLMTimeoutError:
            logger.warning("Direct LLM answer abandoned after its budget elapsed.")
            return {
                "answer": "",
                "sources": [],
                "retrieval_status": "LLM_TIMEOUT",
                "retrieval_message": "",
                "llm_used": False,
                "ml_context_provided": bool(ml_results),
                "warnings": [],
            }
        except Exception as exc:
            logger.warning("Direct LLM answer failed: %s", type(exc).__name__)
            return {
                "answer": "",
                "sources": [],
                "retrieval_status": "LLM_ERROR",
                "retrieval_message": f"LLM call failed: {type(exc).__name__}",
                "llm_used": False,
                "ml_context_provided": bool(ml_results),
                "warnings": [f"LLM call failed: {type(exc).__name__}"],
            }

        return {
            "answer": answer_text.strip(),
            "sources": [],
            "retrieval_status": "DIRECT",
            "retrieval_message": "",
            "llm_used": True,
            "ml_context_provided": bool(ml_results),
            "warnings": [],
        }

    return {
        "answer": "",
        "sources": [],
        "retrieval_status": "RAG_UNAVAILABLE",
        "retrieval_message": "RAG pipeline not initialised.",
        "llm_used": False,
        "ml_context_provided": bool(ml_results),
        "warnings": ["RAG pipeline not available."],
    }


def llm_generate(
    prompt: str,
    *,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """Generate a raw completion with the configured LLM client.

    A thin, **non-raising** wrapper around the RAG project's existing LLM
    client, for callers that need a completion but want to handle an unavailable
    provider themselves (for example the agent's tool planner). Returns ``None``
    — never raising — when the LLM is not configured, the call fails, or the
    optional ``timeout`` budget elapses, so the caller can fall back to a
    deterministic path instead of surfacing an error.

    Credentials stay in the backend environment; only the completion text is
    returned, and any provider error is logged with its credential redacted.
    """
    try:
        pipeline = get_pipeline()
    except RagUnavailableError:
        return None

    llm = getattr(pipeline, "llm_client", None)
    if llm is None or not getattr(llm, "is_configured", False):
        return None

    settings = pipeline.settings
    try:
        text = _call_bounded(
            lambda: llm.generate(
                prompt,
                system=system,
                temperature=(
                    settings.llm_temperature if temperature is None else temperature
                ),
                max_tokens=(
                    settings.llm_max_tokens if max_tokens is None else max_tokens
                ),
            ),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 — the caller falls back instead
        logger.warning(
            "LLM generation failed: %s: %s",
            type(exc).__name__,
            _redact_secrets(str(exc)),
        )
        return None

    text = (text or "").strip()
    return text or None


# ---------------------------------------------------------------------------
# LLM-Driven Smart Answer  (replaces the bare answer_question() call in the
# chat endpoint)
# ---------------------------------------------------------------------------
# Design
# ------
# The goal is to eliminate the rule-based intent classification that currently
# governs the chat endpoint's behavior and replace it with LLM-driven decision-
# making.
#
# Strategy
# ---------
# 1. If the LLM is available, always ask it first with a two-part system
#    prompt: (a) answer the question using general knowledge / farm context,
#    and (b) if the answer would be significantly improved by consulting the
#    agricultural knowledge base, output a special sentinel token so the
#    router knows to also run RAG and produce a follow-up grounded answer.
#
# 2. If the LLM is not available (not configured or the pipeline is down),
#    fall back to the existing answer_question() RAG path — this preserves
#    full backward-compatibility.
#
# 3. If RAG is run (either because the LLM requested it or because the LLM
#    was unavailable), and retrieval returns BELOW_THRESHOLD or EMPTY_INDEX,
#    the technical retrieval message is NEVER sent to the farmer.  Instead:
#    - If the LLM is available, it produces a direct answer anyway.
#    - If the LLM is unavailable, a farmer-friendly message is returned.
#
# 4. The LLM never learns about internal file paths, ingestion commands, or
#    ChromaDB implementation details.
#
# The sentinel approach is a lightweight, single-LLM-call mechanism that lets
# the model decide whether retrieval is worth the extra latency.  It avoids:
# - Two mandatory LLM calls for every message.
# - A dedicated "classifier" LLM call separate from the answer.
# - Any hardcoded keyword lists or intent labels.

_SMART_SYSTEM_PROMPT = """\
You are FarmIQ, a knowledgeable and friendly agricultural assistant serving \
farmers in India. You support both English and Marathi (Devanagari script).

Your primary duties:
1. Respond warmly and naturally to greetings and everyday conversation.
2. Answer general agricultural questions (crops, soil, fertilizers, irrigation, \
pest management, organic farming, drought, weather, market information) using \
your knowledge.
3. Give personalised recommendations when farm data or ML model outputs are \
provided, clearly labelling what is sensor data, what is a model prediction, \
and what is your own guidance.
4. Ask for the specific missing information when a farm-specific recommendation \
truly requires it. Ask only one focused question.
5. Politely redirect off-topic questions without repeating the redirection in \
every turn.

Rules:
- Never invent sensor readings, model predictions, weather observations, or \
government scheme details.
- Label ML predictions as model output, not verified facts.
- Label sensor readings as sensor readings, not measurements you made.
- Keep answers concise and farmer-friendly. Avoid technical jargon unless \
explaining it.
- Answer in the language the farmer used (Marathi in Devanagari if they \
wrote in Marathi; English otherwise).
- For high-stakes decisions (pesticide doses, chemical applications, large \
capital expenditure), recommend consulting a local agricultural officer or KVK.
- Do not expose internal system details, file paths, error messages, or \
ingestion instructions.

IMPORTANT — Document retrieval signal:
If your answer would be significantly improved by consulting specific \
agricultural reference documents (e.g., official ICAR guidelines, state \
agricultural policy, certified organic standards, government scheme details, \
or specific disease/pest identification), include the exact token \
<<NEEDS_RETRIEVAL>> somewhere in your response. The system will then retrieve \
relevant documents and refine your answer. Do NOT include <<NEEDS_RETRIEVAL>> \
for simple greetings, general knowledge questions, or when you already have \
sufficient farm context to give a good answer.
"""

_RETRIEVAL_NEEDED_SENTINEL = "<<NEEDS_RETRIEVAL>>"

# When a farmer-friendly message must replace a technical retrieval failure.
_RETRIEVAL_UNAVAILABLE_MESSAGES = {
    "en": (
        "I don't have specific reference documents for that question right now, "
        "but I can still help based on general agricultural knowledge. "
        "For the most accurate local recommendations, consider consulting your "
        "nearest KVK (Krishi Vigyan Kendra) or agricultural extension officer."
    ),
    "mr": (
        "सध्या या प्रश्नासाठी माझ्याकडे विशिष्ट संदर्भ दस्तऐवज नाहीत, "
        "परंतु सामान्य कृषी ज्ञानाच्या आधारे मी मदत करू शकतो. "
        "अचूक स्थानिक शिफारशींसाठी तुमच्या जवळच्या KVK किंवा कृषी विस्तार "
        "अधिकाऱ्याशी संपर्क साधा."
    ),
}


def smart_answer(
    question: str,
    ml_results: Optional[Dict[str, Any]] = None,
    *,
    top_k: Optional[int] = None,
    language: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    farm_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LLM-driven answer: the model decides whether document retrieval is needed.

    This is the main entry point for ``POST /api/chat``. It replaces the
    previous unconditional RAG call with a two-phase approach:

    Phase 1 — Direct LLM answer
        The LLM is given the question, farm context, ML results, and
        conversation history. It answers naturally. If it includes the
        ``<<NEEDS_RETRIEVAL>>`` sentinel, Phase 2 is triggered.

    Phase 2 — RAG enhancement (only when the LLM requested it)
        The RAG pipeline retrieves relevant passages and the LLM re-answers
        with those passages as additional evidence. If retrieval returns
        nothing useful, the Phase 1 answer is used as-is.

    Fallback — RAG-only (when LLM is unavailable)
        When the LLM is not configured, the traditional ``answer_question()``
        path is used. If retrieval fails, a farmer-friendly message is
        returned instead of the technical retrieval error.

    Both phases share one wall-clock budget (``assistant_llm_budget_seconds``)
    so the answer always arrives before the web/app client's own deadline,
    even when the provider is slow.

    Raises :class:`RagUnavailableError` only when both the LLM AND the RAG
    pipeline are completely unavailable (pipeline import failed, dependencies
    missing, etc.).
    """
    lang = (language or "").strip().lower() or None
    deadline = time.monotonic() + float(get_settings().assistant_llm_budget_seconds)

    # ── Phase 1: Try LLM-driven direct answer ─────────────────────────────
    phase1 = direct_llm_answer(
        question,
        ml_results=ml_results,
        language=lang,
        history=history,
        farm_context=farm_context,
        timeout=remaining_budget(deadline),
    )

    llm_answer_text = (phase1.get("answer") or "").strip()
    llm_was_used = phase1.get("llm_used", False)

    if llm_was_used and llm_answer_text:
        # Check whether the LLM signalled that documents would help.
        needs_retrieval = _RETRIEVAL_NEEDED_SENTINEL in llm_answer_text

        # Remove the sentinel from the user-facing answer text.
        clean_llm_answer = llm_answer_text.replace(_RETRIEVAL_NEEDED_SENTINEL, "").strip()

        if not needs_retrieval:
            # The LLM is confident without documents — return its answer.
            return {**phase1, "answer": clean_llm_answer}

        # ── Phase 2: RAG enhancement (LLM requested it) ───────────────────
        try:
            rag_result = answer_question(
                question,
                ml_results,
                top_k=top_k,
                language=lang,
                history=history,
                farm_context=farm_context,
                timeout=remaining_budget(deadline),
            )
            rag_answer = (rag_result.get("answer") or "").strip()
            rag_status = rag_result.get("retrieval_status", "")
            rag_llm_used = rag_result.get("llm_used", False)

            # ── Intercept unhelpful retrieval messages ─────────────────────
            _bad_prefixes = (
                "The knowledge base does not contain",
                "The knowledge base is empty",
                "Please run the ingestion script",
                "Consider adding relevant agricultural documents",
                "The assistant failed to answer",
                "python scripts/ingest_documents.py",
                "data/raw/",
            )
            retrieval_failed = (
                not rag_answer
                or rag_status in ("BELOW_THRESHOLD", "EMPTY_INDEX")
                or not rag_llm_used
                or any(rag_answer.startswith(p) for p in _bad_prefixes)
                or any(p in rag_answer for p in _bad_prefixes)
            )

            if retrieval_failed:
                # RAG couldn't add value — use the LLM's Phase 1 answer with
                # a note that no specific reference documents were found.
                logger.info(
                    "smart_answer: RAG retrieval unhelpful (status=%s), "
                    "using direct LLM answer.",
                    rag_status,
                )
                return {
                    **phase1,
                    "answer": clean_llm_answer,
                    "retrieval_status": rag_status or "BELOW_THRESHOLD",
                    "retrieval_message": "",
                }

            # Good RAG answer — return it with full source context.
            return {**rag_result}

        except RagUnavailableError as exc:
            logger.info(
                "smart_answer: RAG unavailable during Phase 2 (%s), "
                "using Phase 1 LLM answer.",
                type(exc).__name__,
            )
            # RAG pipeline not available but we have a good LLM answer.
            return {**phase1, "answer": clean_llm_answer}

    # ── Fallback: LLM unavailable — use traditional RAG path ──────────────
    logger.info("smart_answer: LLM not available (status=%s), using RAG fallback.",
                phase1.get("retrieval_status", "unknown"))

    try:
        rag_result = answer_question(
            question,
            ml_results,
            top_k=top_k,
            language=lang,
            history=history,
            farm_context=farm_context,
            timeout=remaining_budget(deadline),
        )
    except RagTimeoutError:
        # Retrieval ran over budget and there is no LLM to phrase an answer, so
        # return the farmer-friendly message instead of a 503.
        friendly_lang = "mr" if lang == "mr" else "en"
        logger.info("smart_answer: RAG fallback abandoned after its budget elapsed.")
        return {
            "answer": _RETRIEVAL_UNAVAILABLE_MESSAGES[friendly_lang],
            "sources": [],
            "retrieval_status": "LLM_TIMEOUT",
            "retrieval_message": "",
            "llm_used": False,
            "ml_context_provided": bool(ml_results),
            "warnings": [],
        }
    except RagUnavailableError:
        raise  # Both LLM and RAG unavailable — let the endpoint return 503.

    rag_answer = (rag_result.get("answer") or "").strip()
    rag_status = rag_result.get("retrieval_status", "")
    rag_llm_used = rag_result.get("llm_used", False)

    # Intercept unhelpful retrieval messages (same check as Phase 2 above).
    _bad_prefixes = (
        "The knowledge base does not contain",
        "The knowledge base is empty",
        "Please run the ingestion script",
        "Consider adding relevant agricultural documents",
        "The assistant failed to answer",
        "python scripts/ingest_documents.py",
        "data/raw/",
    )
    retrieval_failed = (
        not rag_answer
        or rag_status in ("BELOW_THRESHOLD", "EMPTY_INDEX")
        or not rag_llm_used
        or any(rag_answer.startswith(p) for p in _bad_prefixes)
        or any(p in rag_answer for p in _bad_prefixes)
    )

    if retrieval_failed:
        # Return a farmer-friendly message instead of the technical error.
        friendly_lang = "mr" if lang == "mr" else "en"
        friendly_msg = _RETRIEVAL_UNAVAILABLE_MESSAGES[friendly_lang]
        logger.info(
            "smart_answer: RAG retrieval unhelpful (status=%s), "
            "returning friendly fallback message.",
            rag_status,
        )
        return {
            **rag_result,
            "answer": friendly_msg,
            "retrieval_message": "",
        }

    return rag_result
