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

The RAG project keeps its own configuration (``FarmIQ-RAG/.env``) for the LLM
credentials and retrieval parameters; this bridge only locates and instantiates
the pipeline.
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger("farmiq.rag")


class RagUnavailableError(RuntimeError):
    """Raised when the RAG pipeline cannot be loaded or used in this environment.

    The message is safe to show to an operator (it never contains secrets) and
    explains how to enable the assistant.
    """


_lock = threading.Lock()
_pipeline: Any = None  # RAGPipeline | None


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


def get_pipeline() -> Any:
    """Return the process-wide :class:`RAGPipeline`, building it on first use."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _lock:
        if _pipeline is None:
            rag_pipeline = _import_rag_pipeline()
            try:
                _pipeline = rag_pipeline.build_rag_pipeline()
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
) -> Dict[str, Any]:
    """Answer *question* through the RAG pipeline and return a JSON-ready dict.

    ``language`` is an optional answer-language hint ("mr" or "en"); when it is
    omitted the assistant follows the language of the question itself.

    ``history`` is an optional list of recent conversation turns
    (``{"role": "farmer"|"assistant", "text": "..."}``) so that a follow-up
    question such as "which medicine should I use for it?" can be resolved
    against the previous subject. Omit it for a single, self-contained question.

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
        )
    except RagUnavailableError:
        raise
    except Exception as exc:
        logger.exception("RAG answer generation failed.")
        raise RagUnavailableError(
            f"The assistant failed to answer ({type(exc).__name__}: {exc})."
        ) from exc
    return _serialize_result(result)


def get_status() -> Dict[str, Any]:
    """Report assistant availability without raising.

    Returns a dict with ``available`` (pipeline could be loaded) and
    ``indexed`` (the vector index contains at least one chunk), plus the
    embedding model name and the number of indexed chunks. On failure,
    ``available`` is ``False`` and ``message`` explains why.
    """
    try:
        pipeline = get_pipeline()
    except RagUnavailableError as exc:
        return {
            "available": False,
            "indexed": False,
            "index_chunks": 0,
            "llm_configured": False,
            "embedding_model": None,
            "message": str(exc),
        }

    chunks = 0
    try:
        chunks = int(pipeline.retriever.vector_store.count())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read the vector index count: %s", exc)

    return {
        "available": True,
        "indexed": chunks > 0,
        "index_chunks": chunks,
        "llm_configured": bool(getattr(pipeline.llm_client, "is_configured", False)),
        "embedding_model": getattr(pipeline.retriever.embedder, "model_name", None),
        "message": "" if chunks > 0 else "The knowledge base is empty; run ingestion.",
    }
