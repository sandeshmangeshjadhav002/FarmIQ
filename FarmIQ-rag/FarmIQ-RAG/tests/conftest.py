"""Shared pytest fixtures and helpers for FarmIQ-RAG tests.

Tests must never require a paid LLM call or a model download. We provide:

* ``FakeKeywordEmbedder`` – a deterministic, keyword-overlap embedder so that
  cosine similarity reflects shared vocabulary (good enough to assert retrieval
  behaviour without the real SentenceTransformer model).
* Fixtures for a temp ChromaDB path, a vector store, and a fake LLM.
* A small PDF generator using PyMuPDF (skipped if PyMuPDF is absent).
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from pathlib import Path
from typing import List

import pytest

# Make the ``src`` package importable when running pytest from the project root
# or from the tests/ directory.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Deterministic fake embedder
# ---------------------------------------------------------------------------
class FakeKeywordEmbedder:
    """Embedder whose cosine similarity equals normalised keyword overlap.

    Each token is hashed (stable md5) to one of *dim* buckets; the vector is the
    L2-normalised bag-of-words. Two texts sharing many tokens therefore have
    high cosine similarity, which is all the retrieval tests need.
    """

    model_name = "fake-keyword-embedder"

    def __init__(self, dim: int = 512) -> None:
        self._dim = int(dim)

    @property
    def dimension(self) -> int:
        return self._dim

    def _vectorize(self, text: str) -> List[float]:
        vec = [0.0] * self._dim
        for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self._dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def encode(self, texts):
        return [self._vectorize(t) for t in list(texts)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_embedder() -> FakeKeywordEmbedder:
    return FakeKeywordEmbedder()


@pytest.fixture
def tmp_chroma_path(tmp_path: Path) -> Path:
    return tmp_path / "chroma_db"


@pytest.fixture
def collection_name() -> str:
    return "farmiq_test_collection"


def make_vector_store(chroma_path, embedder, collection_name="farmiq_test_collection"):
    """Build a VectorStore wired to a temp path with the given embedder."""
    from src.vector_store import VectorStore

    return VectorStore(
        chroma_path=chroma_path,
        collection_name=collection_name,
        distance_metric="cosine",
        embedder=embedder,
    )


@pytest.fixture
def vector_store(tmp_chroma_path, fake_embedder, collection_name):
    return make_vector_store(tmp_chroma_path, fake_embedder, collection_name)


@pytest.fixture
def fake_llm():
    from src.llm_client import FakeLLMClient

    return FakeLLMClient(response="This is a test answer grounded in the retrieved passages.")


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------
def make_chunk(text: str, source: str, page: int = 1, idx: int = 0, file_type: str = "txt"):
    """Build a :class:`~src.text_chunker.Chunk` with a deterministic ID."""
    from src.text_chunker import Chunk, _make_chunk_id  # type: ignore[attr-defined]

    metadata = {
        "source": source,
        "source_path": f"/data/raw/{source}",
        "page": page,
        "file_type": file_type,
        "chunk_index": idx,
        "chunk_id": _make_chunk_id(source, page, idx, text),
    }
    return Chunk(text=text, metadata=metadata)


def make_pdf(path: Path, pages: List[str]) -> Path:
    """Create a PDF with one page per string. Requires PyMuPDF."""
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        # insert_text places the text on the page as extractable content.
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def requires_chromadb():
    """Skip a test if chromadb is not installed (imported lazily by VectorStore)."""
    pytest.importorskip("chromadb")


def requires_pymupdf():
    pytest.importorskip("pymupdf")
