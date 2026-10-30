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
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import Settings, get_settings

logger = logging.getLogger("farmiq.rag")


class RagUnavailableError(RuntimeError):
    """Raised when the RAG pipeline cannot be loaded or used in this environment.

    The message is safe to show to an operator (it never contains secrets) and
    explains how to enable the assistant.
    """


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

    Raises :class:`RagUnavailableError` when the assistant is not available.
    """
    pipeline = get_pipeline()
    try:
        result = pipeline.answer(
            question,
            ml_results,
            top_k=top_k,
            relevance_threshold=relevance_threshold,
            language=language,
            history=history,
            farm_context=farm_context,
        )
    except RagUnavailableError:
        raise
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
