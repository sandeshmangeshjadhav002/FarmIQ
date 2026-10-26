"""Centralised configuration for the FarmIQ-RAG module.

All settings are read from environment variables (optionally backed by a
``.env`` file in the project root) so that no secrets are ever hard-coded.

Usage::

    from src.config import get_settings

    settings = get_settings()
    print(settings.chroma_path)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is a hard dependency in practice
    load_dotenv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Project root = parent of this ``src`` package directory.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# Default embedding model. The multilingual MiniLM keeps the design extensible
# for Marathi and other Indian languages while remaining lightweight.
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

DEFAULT_COLLECTION_NAME = "farmiq_agri_docs"


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable, tolerating common spellings."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r; falling back to %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r; falling back to %s", name, raw, default)
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Paths are resolved relative to the project root unless an absolute path is
    supplied via the environment. The same ``EMBEDDING_MODEL`` is used for both
    ingestion and retrieval, which is essential for correct vector search.
    """

    # --- Paths ---------------------------------------------------------------
    data_raw_dir: Path
    data_processed_dir: Path
    chroma_path: Path

    # --- Vector store --------------------------------------------------------
    collection_name: str
    # Cosine distance is used so that ``distance`` in [0, 2] maps to a
    # similarity score ``1 - distance`` in [-1, 1].
    distance_metric: str = "cosine"

    # --- Embeddings ----------------------------------------------------------
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    # Cache directory for HuggingFace models (None -> library default).
    hf_cache_dir: Optional[Path] = None

    # --- Chunking ------------------------------------------------------------
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # --- Retrieval -----------------------------------------------------------
    top_k: int = 5
    # Minimum cosine similarity (0..1) for a chunk to be considered relevant.
    relevance_threshold: float = 0.30

    # --- LLM -----------------------------------------------------------------
    llm_provider: str = "openai"
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    # Optional base URL for OpenAI-compatible providers (Together, Groq, vLLM, ...).
    llm_base_url: Optional[str] = None
    llm_temperature: float = 0.2
    llm_max_tokens: int = 800
    llm_request_timeout: float = 60.0

    # --- Logging -------------------------------------------------------------
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        # Never log or store secrets. We only validate that paths exist as dirs.
        if not self.llm_api_key:
            logger.debug("LLM_API_KEY is not set; answer generation will be unavailable.")

    @property
    def llm_configured(self) -> bool:
        """True when an LLM provider can be used for answer generation."""
        return bool(self.llm_api_key) and bool(self.llm_model)

    def ensure_dirs(self) -> None:
        """Create the on-disk directories used by the module if missing."""
        self.data_raw_dir.mkdir(parents=True, exist_ok=True)
        self.data_processed_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)


def _resolve_path(raw: Optional[str], default: Path) -> Path:
    if raw is None or raw.strip() == "":
        return default
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load .env (if present) and build a cached :class:`Settings` instance."""
    if load_dotenv is not None:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
        # Still call load_dotenv() so a system-level .env is honoured too.
        load_dotenv()

    embedding_model = os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL

    settings = Settings(
        data_raw_dir=_resolve_path(os.getenv("DATA_RAW_DIR"), PROJECT_ROOT / "data" / "raw"),
        data_processed_dir=_resolve_path(
            os.getenv("DATA_PROCESSED_DIR"), PROJECT_ROOT / "data" / "processed"
        ),
        chroma_path=_resolve_path(os.getenv("CHROMA_PATH"), PROJECT_ROOT / "chroma_db"),
        collection_name=os.getenv("COLLECTION_NAME") or DEFAULT_COLLECTION_NAME,
        distance_metric=os.getenv("CHROMA_DISTANCE_METRIC") or "cosine",
        embedding_model=embedding_model,
        hf_cache_dir=_resolve_path(os.getenv("HF_HOME"), Path(os.getenv("HF_HOME", "")))
        if os.getenv("HF_HOME")
        else None,
        chunk_size=_env_int("CHUNK_SIZE", 1000),
        chunk_overlap=_env_int("CHUNK_OVERLAP", 200),
        top_k=_env_int("TOP_K", 5),
        relevance_threshold=_env_float("RELEVANCE_THRESHOLD", 0.30),
        llm_provider=os.getenv("LLM_PROVIDER") or "openai",
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_model=os.getenv("LLM_MODEL") or "gpt-4o-mini",
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.2),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", 800),
        llm_request_timeout=_env_float("LLM_REQUEST_TIMEOUT", 60.0),
        log_level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
    )

    # Configure root logging once.
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return settings


def reset_settings_cache() -> None:
    """Clear the cached settings (useful for tests that mutate env vars)."""
    get_settings.cache_clear()
