"""Semantic retrieval for FarmIQ-RAG.

Accepts a natural-language question, embeds it with the shared
:class:`~src.embeddings.Embedder`, queries the :class:`~src.vector_store.VectorStore`,
applies a configurable relevance threshold, and returns a
:class:`RetrievalResult` that clearly distinguishes three states:

* **Relevant passages found** — normal answer-generation path.
* **No relevant passages** — above-threshold results exist but none exceed the
  configured similarity cutoff; the pipeline should report insufficient evidence
  rather than fabricating an answer.
* **Index empty** — nothing has been ingested yet; caller should display a
  helpful message prompting ingestion.

Design notes
------------
* The embedder that is injected here **must** be the same instance/model used
  during ingestion; the VectorStore validates nothing about this — it is the
  caller's responsibility to use ``get_embedder()`` consistently.
* ``top_k`` and ``relevance_threshold`` default to the values in
  :class:`~src.config.Settings` but can be overridden per call for programmatic
  use.
* Retrieved items are returned in descending similarity order.
* Source metadata (filename, page) travels with every item so the RAG pipeline
  and CLI can cite passages without extra lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

from src.embeddings import Embedder
from src.vector_store import RetrievedItem, VectorStore

logger = logging.getLogger(__name__)


class RetrievalStatus(Enum):
    """Outcome of a retrieval attempt."""
    OK = auto()               # ≥1 item above threshold
    BELOW_THRESHOLD = auto()  # results exist but none scored high enough
    EMPTY_INDEX = auto()      # no documents have been ingested


@dataclass
class RetrievalResult:
    """Outcome of a single retrieval call.

    ``items`` is non-empty only when ``status == RetrievalStatus.OK``.
    ``message`` carries a human-readable explanation for non-OK states so the
    RAG pipeline can include it in its response without inventing context.
    """

    status: RetrievalStatus
    items: List[RetrievedItem] = field(default_factory=list)
    message: str = ""
    query: str = ""

    @property
    def has_results(self) -> bool:
        return self.status == RetrievalStatus.OK and bool(self.items)

    def top_item(self) -> Optional[RetrievedItem]:
        return self.items[0] if self.items else None


class Retriever:
    """Semantic retriever backed by a :class:`~src.vector_store.VectorStore`."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: Embedder,
        top_k: int = 5,
        relevance_threshold: float = 0.30,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if not (0.0 <= relevance_threshold <= 1.0):
            raise ValueError("relevance_threshold must be in [0.0, 1.0]")
        self.vector_store = vector_store
        self.embedder = embedder
        self.top_k = top_k
        self.relevance_threshold = relevance_threshold

    def retrieve(
        self,
        question: str,
        top_k: Optional[int] = None,
        relevance_threshold: Optional[float] = None,
    ) -> RetrievalResult:
        """Embed *question* and return relevant passages from the index.

        Parameters
        ----------
        question:
            The farmer's natural-language question.
        top_k:
            Override the instance-level ``top_k`` for this call.
        relevance_threshold:
            Override the instance-level threshold for this call.

        Returns
        -------
        :class:`RetrievalResult` whose ``status`` describes the outcome.
        """
        question = question.strip()
        if not question:
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message="An empty question was supplied.",
                query=question,
            )

        k = int(top_k if top_k is not None else self.top_k)
        threshold = float(
            relevance_threshold if relevance_threshold is not None else self.relevance_threshold
        )

        # ── 1. Guard: empty index ─────────────────────────────────────────────
        if self.vector_store.is_empty():
            logger.warning("Retrieval attempted but the index is empty.")
            return RetrievalResult(
                status=RetrievalStatus.EMPTY_INDEX,
                message=(
                    "The knowledge base is empty. "
                    "Please run the ingestion script first:\n"
                    "    python scripts/ingest_documents.py"
                ),
                query=question,
            )

        # ── 2. Embed question ─────────────────────────────────────────────────
        logger.debug("Embedding question for retrieval (top_k=%s, threshold=%.2f).", k, threshold)
        try:
            embeddings = self.embedder.encode([question])
        except Exception as exc:
            logger.error("Failed to embed question: %s", exc)
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message=f"Embedding failed: {exc}",
                query=question,
            )

        if not embeddings:
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message="Embedder returned no vectors for the question.",
                query=question,
            )

        # ── 3. Vector search ──────────────────────────────────────────────────
        try:
            raw_items = self.vector_store.query_by_embedding(
                embeddings[0],
                top_k=k,
            )
        except Exception as exc:
            logger.error("Vector store query failed: %s", exc)
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message=f"Vector search failed: {exc}",
                query=question,
            )

        if not raw_items:
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message=(
                    "The knowledge base does not contain information "
                    "relevant to your question."
                ),
                query=question,
            )

        # ── 4. Apply relevance threshold ──────────────────────────────────────
        filtered = [item for item in raw_items if item.similarity >= threshold]
        if not filtered:
            best = raw_items[0].similarity if raw_items else 0.0
            logger.info(
                "No chunks above threshold %.2f (best similarity: %.3f) for question: %r",
                threshold,
                best,
                question[:80],
            )
            return RetrievalResult(
                status=RetrievalStatus.BELOW_THRESHOLD,
                message=(
                    "The knowledge base does not contain sufficient information "
                    "to answer this question confidently. "
                    "Consider adding relevant agricultural documents to data/raw/ "
                    "and re-running ingestion."
                ),
                query=question,
            )

        # ── 5. Sort descending and return ─────────────────────────────────────
        filtered.sort(key=lambda x: x.similarity, reverse=True)
        logger.info(
            "Retrieved %s relevant chunk(s) (top similarity: %.3f) for question: %r",
            len(filtered),
            filtered[0].similarity,
            question[:80],
        )
        return RetrievalResult(
            status=RetrievalStatus.OK,
            items=filtered,
            message="",
            query=question,
        )
