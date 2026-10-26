"""Tests for the retriever, vector store, and chunker.

Coverage
--------
* Text chunking — overlap, metadata preservation, deterministic IDs.
* Vector-store persistence — data survives a new instance on the same path.
* Retrieval from indexed documents — relevant passages surface first.
* Empty knowledge base handling — EMPTY_INDEX status with helpful message.
* Relevance threshold — irrelevant content returns BELOW_THRESHOLD.
* top-k — result count respects the limit.
"""

from __future__ import annotations

import pytest

from src.text_chunker import TextChunker, chunk_documents
from src.document_loader import Document


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------
class TestTextChunker:
    def test_split_single_document_preserves_metadata(self) -> None:
        doc = Document(
            text="A B C D E F G H I J K L M N O P Q R S T U V W X Y Z " * 5,
            metadata={"source": "agri.pdf", "page": 3, "source_path": "/raw/agri.pdf"},
        )
        chunks = TextChunker(chunk_size=80, chunk_overlap=20).split_documents([doc])
        assert len(chunks) >= 2
        for c in chunks:
            assert c.metadata["source"] == "agri.pdf"
            assert c.metadata["page"] == 3
            assert "chunk_index" in c.metadata
            assert isinstance(c.metadata["chunk_id"], str) and len(c.metadata["chunk_id"]) > 0

    def test_chunk_ids_are_deterministic(self) -> None:
        doc = Document(text="alpha beta gamma delta epsilon zeta eta theta.", metadata={"source": "x.txt", "page": 1})
        chunker = TextChunker(chunk_size=40, chunk_overlap=10)
        first = chunker.split_documents([doc])
        second = chunker.split_documents([doc])
        assert [c.chunk_id for c in first] == [c.chunk_id for c in second]

    def test_chunk_index_increments_per_page(self) -> None:
        doc = Document(text="word " * 80, metadata={"source": "x.txt", "page": 1})
        chunks = TextChunker(chunk_size=50, chunk_overlap=10).split_documents([doc])
        indices = [c.metadata["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_overlap_creates_shared_content(self) -> None:
        doc = Document(text="alpha beta gamma delta epsilon zeta eta theta iota " * 3, metadata={"source": "x.txt", "page": 1})
        chunks = TextChunker(chunk_size=60, chunk_overlap=30).split_documents([doc])
        assert len(chunks) >= 2
        overlap_found = False
        for prev, curr in zip(chunks, chunks[1:]):
            # Overlapping chunks should share some trailing/leading tokens.
            common = set(prev.text.split()) & set(curr.text.split())
            if common:
                overlap_found = True
        assert overlap_found, "Expected overlapping tokens between consecutive chunks"

    def test_empty_text_produces_no_chunks(self) -> None:
        doc = Document(text="", metadata={"source": "x.txt", "page": 1})
        assert TextChunker().split_documents([doc]) == []

    def test_invalid_overlap_raises(self) -> None:
        with pytest.raises(ValueError):
            TextChunker(chunk_size=100, chunk_overlap=100)

    def test_invalid_size_raises(self) -> None:
        with pytest.raises(ValueError):
            TextChunker(chunk_size=0, chunk_overlap=0)


# ---------------------------------------------------------------------------
# Vector store + retrieval
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_store(vector_store):
    """A vector store with one relevant and one irrelevant chunk."""
    requires = pytest.importorskip("chromadb")
    from tests.conftest import make_chunk

    chunks = [
        make_chunk(
            "Soybean irrigation should be done weekly during the flowering stage.",
            source="soybean_irrigation.pdf",
            page=4,
        ),
        make_chunk(
            "The Eiffel Tower is located in Paris, France and was built in 1889.",
            source="unrelated.txt",
            page=1,
        ),
    ]
    vector_store.add_chunks(chunks)
    return vector_store


class TestVectorStore:
    def test_add_chunks_increases_count(self, vector_store):
        pytest.importorskip("chromadb")
        from tests.conftest import make_chunk

        assert vector_store.count() == 0
        vector_store.add_chunks([make_chunk("hello world", "a.txt", 1)])
        assert vector_store.count() == 1

    def test_persistence_across_new_instance(self, tmp_chroma_path, fake_embedder, collection_name):
        """A fresh VectorStore on the same path should see persisted data."""
        pytest.importorskip("chromadb")
        from tests.conftest import make_chunk, make_vector_store

        store_a = make_vector_store(tmp_chroma_path, fake_embedder, collection_name)
        store_a.add_chunks([make_chunk("Soybean needs adequate water during flowering.", "a.txt", 1)])
        n = store_a.count()
        assert n == 1

        store_b = make_vector_store(tmp_chroma_path, fake_embedder, collection_name)
        assert store_b.count() == n
        items = store_b.query("soybean water flowering", top_k=1)
        assert len(items) == 1
        assert "Soybean" in items[0].text

    def test_idempotent_reingestion(self, vector_store):
        """Upserting the same chunk twice must not duplicate the record."""
        pytest.importorskip("chromadb")
        from tests.conftest import make_chunk

        chunk = make_chunk("duplicate content here", "a.txt", 1)
        vector_store.add_chunks([chunk])
        vector_store.add_chunks([chunk])
        assert vector_store.count() == 1

    def test_rebuild_clears_collection(self, vector_store):
        pytest.importorskip("chromadb")
        from tests.conftest import make_chunk

        vector_store.add_chunks([make_chunk("content one", "a.txt", 1)])
        assert vector_store.count() >= 1
        vector_store.rebuild()
        assert vector_store.count() == 0

    def test_list_sources(self, vector_store):
        pytest.importorskip("chromadb")
        from tests.conftest import make_chunk

        vector_store.add_chunks(
            [
                make_chunk("alpha", "a.txt", 1),
                make_chunk("beta", "b.txt", 1),
                make_chunk("gamma", "a.txt", 2),
            ]
        )
        sources = vector_store.list_sources()
        assert sources == {"a.txt", "b.txt"}

    def test_query_returns_similarity_in_range(self, populated_store):
        items = populated_store.query("soybean irrigation flowering", top_k=2)
        assert len(items) == 2
        for item in items:
            assert -1.0 <= item.similarity <= 1.0


class TestRetriever:
    def test_retrieves_relevant_passage_first(self, populated_store):
        from src.retriever import Retriever

        retriever = Retriever(populated_store, embedder=populated_store.embedder, top_k=2, relevance_threshold=0.10)
        result = retriever.retrieve("How should I manage irrigation for a soybean crop?")
        assert result.status.name == "OK"
        assert result.has_results
        assert result.top_item().source == "soybean_irrigation.pdf"
        assert result.top_item().page == 4

    def test_top_k_limits_results(self, populated_store):
        from src.retriever import Retriever

        retriever = Retriever(populated_store, embedder=populated_store.embedder, top_k=5, relevance_threshold=0.0)
        result = retriever.retrieve("soybean irrigation", top_k=1)
        assert result.status.name == "OK"
        assert len(result.items) == 1

    def test_empty_index_status(self, vector_store):
        from src.retriever import Retriever

        retriever = Retriever(vector_store, embedder=vector_store.embedder)
        result = retriever.retrieve("anything")
        assert result.status.name == "EMPTY_INDEX"
        assert "ingest" in result.message.lower()
        assert not result.has_results

    def test_below_threshold_status(self, populated_store):
        from src.retriever import Retriever

        # Very high threshold so even the relevant chunk is rejected.
        retriever = Retriever(populated_store, embedder=populated_store.embedder, relevance_threshold=0.99)
        result = retriever.retrieve("quantum physics lecture notes")
        assert result.status.name == "BELOW_THRESHOLD"
        assert "insufficient" in result.message.lower() or "not contain" in result.message.lower()
        assert not result.has_results

    def test_metadata_preserved_in_retrieved_item(self, populated_store):
        from src.retriever import Retriever

        retriever = Retriever(populated_store, embedder=populated_store.embedder, relevance_threshold=0.0)
        result = retriever.retrieve("soybean irrigation")
        assert result.status.name == "OK"
        top = result.top_item()
        assert top.source == "soybean_irrigation.pdf"
        assert top.page == 4
        assert isinstance(top.chunk_id, str) and top.chunk_id

    def test_empty_question_returns_below_threshold(self, populated_store):
        from src.retriever import Retriever

        retriever = Retriever(populated_store, embedder=populated_store.embedder)
        result = retriever.retrieve("   ")
        assert result.status.name == "BELOW_THRESHOLD"

    def test_threshold_override_per_call(self, populated_store):
        from src.retriever import Retriever

        retriever = Retriever(populated_store, embedder=populated_store.embedder, relevance_threshold=0.99)
        # Override threshold low for this call → should now find the chunk.
        result = retriever.retrieve("soybean irrigation flowering", relevance_threshold=0.0)
        assert result.status.name == "OK"
        assert result.has_results
