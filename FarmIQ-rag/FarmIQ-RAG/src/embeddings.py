"""Embedding generation for FarmIQ-RAG.

A thin wrapper around ``sentence-transformers`` that is shared by both the
ingestion pipeline and the retriever. Using the *same* model instance and
configuration for both is essential: vectors created with one embedding model
cannot be meaningfully searched with another.

The wrapper exposes a small, explicit interface (``encode``) so that the
underlying library can be swapped later without touching the rest of the
codebase. Tests inject a fake embedder that implements the same interface.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Protocol, Sequence, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    """Embedding interface used by the vector store and retriever."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode(self, texts: Sequence[str]) -> List[List[float]]: ...


class SentenceTransformerEmbedder:
    """Concrete embedder backed by ``sentence-transformers``.

    The model is loaded lazily on first use (and once per instance) so that
    importing this module never triggers a heavyweight download.
    """

    def __init__(
        self,
        model_name: str,
        cache_dir: Optional[str] = None,
        device: Optional[str] = None,
        normalize_embeddings: bool = True,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._device = device
        self._normalize = normalize_embeddings
        self._model = None
        self._dimension: Optional[int] = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "sentence-transformers is required to generate embeddings. "
                "Install it via: pip install sentence-transformers"
            ) from exc

        logger.info("Loading embedding model '%s' (first use may download weights).", self._model_name)
        self._model = SentenceTransformer(
            self._model_name,
            cache_folder=self._cache_dir,
            device=self._device,
        )
        # Determine dimension from a tiny probe so callers can validate stores.
        probe = self._model.encode(["dimension probe"], normalize_embeddings=self._normalize)
        self._dimension = int(probe.shape[1])
        logger.info("Embedding model ready (dimension=%s).", self._dimension)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        assert self._dimension is not None
        return self._dimension

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        assert self._model is not None
        # list(texts) guards against generators that would be consumed once.
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=self._normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()


def build_embedder(
    model_name: str,
    cache_dir: Optional[str] = None,
    device: Optional[str] = None,
) -> Embedder:
    """Factory used by the rest of the module to obtain an :class:`Embedder`.

    Keeping construction in one place makes it easy to swap implementations
    (e.g. a different backend) without changing call sites.
    """
    return SentenceTransformerEmbedder(
        model_name=model_name,
        cache_dir=cache_dir,
        device=device,
        normalize_embeddings=True,
    )
