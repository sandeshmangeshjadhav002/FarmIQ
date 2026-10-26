"""Text chunking for FarmIQ-RAG.

Splits :class:`~src.document_loader.Document` objects into overlapping text
chunks using LangChain's ``RecursiveCharacterTextSplitter`` while preserving
the source metadata (filename, page number) on every chunk so that retrieved
passages can be cited accurately.

The chunker is deliberately decoupled from the document loader and the vector
store: it takes documents in, returns chunks out.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from src.document_loader import Document

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """An overlapping text slice with provenance metadata.

    ``metadata`` inherits the parent document's ``source``, ``source_path``,
    ``page`` (when present) and adds ``chunk_index`` and a stable ``chunk_id``
    used to avoid duplicating records in the vector store.
    """

    text: str
    metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return str(self.metadata.get("chunk_id", ""))

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))

    @property
    def page(self) -> Optional[int]:
        val = self.metadata.get("page")
        return int(val) if val is not None else None


def _make_chunk_id(source: str, page: Optional[int], chunk_index: int, text: str) -> str:
    """Deterministic ID so re-ingesting the same content upserts instead of duplicating."""
    raw = f"{source}|{page}|{chunk_index}|{text[:256]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


class TextChunker:
    """Wraps LangChain's recursive character splitter with metadata handling."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[Sequence[str]] = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be in [0, chunk_size)")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = list(separators) if separators else None
        self._splitter = self._build_splitter()

    def _build_splitter(self):
        """Build the LangChain splitter lazily.

        Imported lazily so this module can be imported in test environments
        where LangChain text-splitters is not yet installed.
        """
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
        except Exception as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "langchain-text-splitters is required for chunking. "
                "Install it via: pip install langchain-text-splitters"
            ) from exc

        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False,
            strip_whitespace=True,
        )

    def split_text(self, text: str) -> List[str]:
        """Split a raw string into overlapping chunks."""
        if not text:
            return []
        return [c for c in self._splitter.split_text(text) if c and c.strip()]

    def split_documents(self, documents: Sequence[Document]) -> List[Chunk]:
        """Split a sequence of :class:`Document` objects into :class:`Chunk` objects.

        Each produced chunk carries the parent document's metadata plus a
        ``chunk_index`` (per source+page) and a deterministic ``chunk_id``.
        """
        chunks: List[Chunk] = []
        # Counter keyed by (source, page) so chunk indices are stable per page.
        per_key_index: Dict[tuple, int] = {}

        for doc in documents:
            pieces = self.split_text(doc.text)
            if not pieces:
                logger.debug("Document %s produced no chunks; skipped.", doc.source)
                continue

            key = (doc.source, doc.page)
            for piece in pieces:
                idx = per_key_index.get(key, 0)
                per_key_index[key] = idx + 1

                meta = dict(doc.metadata)
                meta["chunk_index"] = idx
                meta["chunk_id"] = _make_chunk_id(doc.source, doc.page, idx, piece)
                chunks.append(Chunk(text=piece, metadata=meta))

        logger.info("Produced %s chunk(s) from %s document section(s).", len(chunks), len(documents))
        return chunks


def chunk_documents(
    documents: Sequence[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[Chunk]:
    """Convenience wrapper: chunk documents with the given parameters."""
    return TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap).split_documents(documents)
