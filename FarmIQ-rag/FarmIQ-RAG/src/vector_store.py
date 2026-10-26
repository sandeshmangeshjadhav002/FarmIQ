"""Persistent vector storage for FarmIQ-RAG (ChromaDB).

Wraps a ChromaDB persistent client so that the rest of the codebase never
deals with Chroma specifics directly. Responsibilities:

* Create / open a persistent collection at ``CHROMA_PATH``.
* Embed chunks with the shared :class:`~src.embeddings.Embedder` and upsert
  them with **deterministic chunk IDs** so re-ingestion updates rather than
  duplicates identical content.
* Batch upserts to stay within Chroma's recommended request sizes.
* Query by question embedding and return items with a normalised similarity
  score (0..1) computed from the cosine distance.
* Provide ``rebuild`` (drop + recreate) and ``reset`` operations.

The embedder is injected so that tests can substitute a lightweight fake and
avoid downloading the real model.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from src.embeddings import Embedder
from src.text_chunker import Chunk

logger = logging.getLogger(__name__)


@dataclass
class RetrievedItem:
    """A single retrieval hit with provenance and a normalised similarity."""

    text: str
    metadata: Dict[str, object]
    similarity: float
    chunk_id: str

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", "unknown"))

    @property
    def page(self) -> Optional[int]:
        val = self.metadata.get("page")
        return int(val) if val is not None else None


def _sanitize_metadata(metadata: Dict[str, object]) -> Dict[str, object]:
    """Coerce metadata values to Chroma-compatible primitives (drop None)."""
    clean: Dict[str, object] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[str(key)] = value
        else:
            clean[str(key)] = str(value)
    return clean


def _distance_to_similarity(distance: float, metric: str) -> float:
    """Convert a Chroma distance to a 0..1 similarity score.

    For ``cosine`` space Chroma returns ``1 - cos_sim`` in [0, 2], so
    ``similarity = 1 - distance`` (clamped to [-1, 1]). For ``l2`` we apply a
    crude reciprocal transform; cosine is the recommended default.
    """
    if metric == "cosine":
        sim = 1.0 - float(distance)
        return max(-1.0, min(1.0, sim))
    # For non-cosine metrics a lower distance is still "more similar"; expose a
    # bounded proxy so the threshold logic stays meaningful.
    return max(0.0, min(1.0, 1.0 / (1.0 + float(distance))))


class VectorStore:
    """Persistent ChromaDB-backed store of embedded agricultural chunks."""

    def __init__(
        self,
        chroma_path: Path | str,
        collection_name: str,
        distance_metric: str,
        embedder: Embedder,
        batch_size: int = 256,
    ) -> None:
        self.chroma_path = Path(chroma_path)
        self.collection_name = collection_name
        self.distance_metric = distance_metric
        self.embedder = embedder
        self.batch_size = max(1, int(batch_size))
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------ client
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        import chromadb
        from chromadb import Settings

        # Disable anonymised telemetry for a private, offline-friendly store.
        os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        return self._client

    def _ensure_collection(self):
        if self._collection is None:
            client = self._ensure_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": self.distance_metric},
            )
        return self._collection

    # ------------------------------------------------------------------ writes
    def add_chunks(self, chunks: Sequence[Chunk]) -> int:
        """Embed and upsert chunks. Returns the number of chunks stored.

        Because chunk IDs are deterministic, calling this with the same
        content is idempotent: existing records are overwritten in place rather
        than duplicated.
        """
        if not chunks:
            return 0
        collection = self._ensure_collection()

        texts = [c.text for c in chunks]
        ids = [c.chunk_id for c in chunks]
        metadatas = [_sanitize_metadata(c.metadata) for c in chunks]
        embeddings = self.embedder.encode(texts)
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedder returned {len(embeddings)} vectors for {len(texts)} texts"
            )

        total = 0
        for start in range(0, len(ids), self.batch_size):
            end = start + self.batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=texts[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end],
            )
            total += end - start
        logger.info("Upserted %s chunk(s) into '%s'.", total, self.collection_name)
        return total

    # ------------------------------------------------------------------ reads
    def count(self) -> int:
        try:
            return int(self._ensure_collection().count())
        except Exception as exc:
            logger.warning("count() failed: %s", exc)
            return 0

    def is_empty(self) -> bool:
        return self.count() == 0

    def list_sources(self) -> Set[str]:
        """Return the set of source filenames currently in the collection."""
        if self.is_empty():
            return set()
        try:
            result = self._ensure_collection().get(include=["metadatas"])
        except Exception as exc:  # pragma: no cover
            logger.warning("list_sources() failed: %s", exc)
            return set()
        sources: Set[str] = set()
        for meta in result.get("metadatas", []) or []:
            if meta and "source" in meta:
                sources.add(str(meta["source"]))
        return sources

    def query(
        self,
        query_text: str,
        top_k: Optional[int] = None,
    ) -> List[RetrievedItem]:
        """Embed ``query_text`` and return the top-k matching items."""
        embeddings = self.embedder.encode([query_text])
        if not embeddings:
            return []
        return self.query_by_embedding(embeddings[0], top_k=top_k)

    def query_by_embedding(
        self,
        query_embedding: Sequence[float],
        top_k: Optional[int] = None,
    ) -> List[RetrievedItem]:
        """Query using a precomputed embedding (used by the retriever)."""
        if self.is_empty():
            return []
        k = int(top_k if top_k is not None else 5)
        collection = self._ensure_collection()
        raw = collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        return self._parse_query_result(raw)

    def _parse_query_result(self, raw: Dict) -> List[RetrievedItem]:
        ids_block = (raw.get("ids") or [[]])[0]
        docs_block = (raw.get("documents") or [[]])[0]
        meta_block = (raw.get("metadatas") or [[]])[0]
        dist_block = (raw.get("distances") or [[]])[0]

        items: List[RetrievedItem] = []
        for i in range(len(ids_block)):
            meta = meta_block[i] if i < len(meta_block) else {}
            distance = dist_block[i] if i < len(dist_block) else 1.0
            chunk_id = ids_block[i] if i < len(ids_block) else ""
            doc = docs_block[i] if i < len(docs_block) else ""
            items.append(
                RetrievedItem(
                    text=str(doc),
                    metadata=dict(meta or {}),
                    similarity=_distance_to_similarity(float(distance), self.distance_metric),
                    chunk_id=str(chunk_id),
                )
            )
        return items

    # ------------------------------------------------------------- maintenance
    def rebuild(self) -> None:
        """Drop the collection and recreate it empty (removes orphaned chunks)."""
        client = self._ensure_client()
        try:
            client.delete_collection(name=self.collection_name)
            logger.info("Deleted existing collection '%s' for rebuild.", self.collection_name)
        except Exception as exc:
            logger.debug("No existing collection to delete (%s).", exc)
        self._collection = None
        self._ensure_collection()

    def reset(self) -> None:
        """Wipe all collections in this Chroma path (use with care)."""
        client = self._ensure_client()
        try:
            client.reset()
        except Exception as exc:  # pragma: no cover
            logger.warning("reset() failed (%s); falling back to rebuild.", exc)
            self.rebuild()
        self._collection = None
