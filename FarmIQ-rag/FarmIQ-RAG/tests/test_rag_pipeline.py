"""Tests for the RAG pipeline, LLM client, and source formatter.

Coverage
--------
* Normal answer generation — answer text, sources, llm_used flag.
* Source references returned with the answer.
* Empty knowledge base — EMPTY_INDEX propagated, LLM not called.
* Missing API credentials — graceful degradation without fabricated answer.
* Optional ML context — ml_results=None works; non-null fields surfaced;
  null fields not surfaced; wrong type ignored.
* ML context dict is not modified.
* Answer contains the citation legend when sources exist.
* Source formatter — context block, citation legend, no-evidence warning.
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_pipeline(vector_store, fake_llm):
    """Wire a RAGPipeline with injected fakes (no model download, no network)."""
    from src.config import get_settings, reset_settings_cache
    from src.rag_pipeline import RAGPipeline
    from src.retriever import Retriever

    retriever = Retriever(
        vector_store=vector_store,
        embedder=vector_store.embedder,
        top_k=3,
        relevance_threshold=0.0,  # threshold=0 so every chunk is "relevant"
    )
    return RAGPipeline(retriever=retriever, llm_client=fake_llm)


def _add_agri_chunk(vector_store, text, source="irrigation_guide.pdf", page=5):
    from tests.conftest import make_chunk

    chunk = make_chunk(text, source=source, page=page)
    vector_store.add_chunks([chunk])


# ---------------------------------------------------------------------------
# Normal answer generation
# ---------------------------------------------------------------------------
class TestRAGPipelineAnswer:
    def test_answer_is_non_empty(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Soybean crops need 450–700 mm of rainfall or equivalent irrigation.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("How much water does soybean need?")
        assert result.has_answer
        assert result.llm_used is True
        assert result.retrieval_status.name == "OK"

    def test_sources_returned_with_answer(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Drip irrigation reduces water use by 40%.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("irrigation for soybean")
        assert len(result.sources) >= 1
        assert result.sources[0].source == "irrigation_guide.pdf"
        assert result.sources[0].page == 5

    def test_citation_legend_appended_to_answer(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Furrow irrigation works well for row crops.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("irrigation methods")
        assert "Sources used:" in result.answer

    def test_llm_called_once_per_question(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Urea provides nitrogen for crop growth.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        pipeline.answer("What does urea do?")
        assert len(fake_llm.calls) == 1


# ---------------------------------------------------------------------------
# Conversation history (follow-up questions)
# ---------------------------------------------------------------------------
class TestConversationHistory:
    def test_previous_question_is_added_to_the_retrieval_query(self):
        from src.rag_pipeline import _build_retrieval_query

        query = _build_retrieval_query(
            "which medicine should i use for it",
            "",
            "my tomato leaves have brown spots",
        )
        # The new question still dominates, but the earlier subject is present
        # so the embedding has something to match.
        assert query.startswith("which medicine should i use for it")
        assert "my tomato leaves have brown spots" in query

    def test_retrieval_query_unchanged_without_history(self):
        from src.rag_pipeline import _build_retrieval_query

        assert (
            _build_retrieval_query("How much water does soybean need?", "")
            == "How much water does soybean need?"
        )

    def test_prompt_includes_the_recent_conversation(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(
            vector_store,
            "Early blight of tomato is managed with crop rotation and resistant varieties.",
        )
        pipeline = _build_pipeline(vector_store, fake_llm)
        pipeline.answer(
            "which medicine should i use for it",
            history=[
                {"role": "farmer", "text": "my tomato leaves have brown spots"},
                {"role": "assistant", "text": "That sounds like early blight."},
            ],
        )
        prompt = fake_llm.calls[0]["prompt"]
        assert "Recent conversation" in prompt
        assert "my tomato leaves have brown spots" in prompt

    def test_malformed_history_is_ignored(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Urea provides nitrogen for crop growth.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("What does urea do?", history="not-a-list")
        assert result.has_answer
        assert "Recent conversation" not in fake_llm.calls[0]["prompt"]

    def test_only_the_most_recent_turns_are_kept(self):
        from src.rag_pipeline import _MAX_HISTORY_TURNS, _normalise_history

        turns = _normalise_history(
            [{"role": "farmer", "text": f"question {i}"} for i in range(20)]
        )
        assert len(turns) == _MAX_HISTORY_TURNS
        assert turns[-1]["text"] == "question 19"


# ---------------------------------------------------------------------------
# Empty knowledge base
# ---------------------------------------------------------------------------
class TestEmptyKnowledgeBase:
    def test_empty_index_returns_empty_status(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("How much water does soybean need?")
        assert result.retrieval_status.name == "EMPTY_INDEX"
        assert not result.llm_used
        assert "ingest" in result.answer.lower() or "empty" in result.answer.lower()

    def test_llm_not_called_on_empty_index(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        pipeline = _build_pipeline(vector_store, fake_llm)
        pipeline.answer("crop disease question")
        assert len(fake_llm.calls) == 0


# ---------------------------------------------------------------------------
# Missing API credentials
# ---------------------------------------------------------------------------
class TestMissingCredentials:
    def test_unconfigured_llm_returns_passages_not_error(self, vector_store):
        pytest.importorskip("chromadb")
        from src.llm_client import FakeLLMClient

        unconfigured_llm = FakeLLMClient(configured=False)
        _add_agri_chunk(vector_store, "Phosphorus deficiency causes purple leaves in maize.")
        pipeline = _build_pipeline(vector_store, unconfigured_llm)
        result = pipeline.answer("Why are my maize leaves purple?")
        assert not result.llm_used
        assert result.has_answer  # returns raw passages, not empty
        assert any("LLM" in w or "api" in w.lower() or "configured" in w.lower() for w in result.warnings)

    def test_unconfigured_llm_does_not_call_generate(self, vector_store):
        pytest.importorskip("chromadb")
        from src.llm_client import FakeLLMClient

        unconfigured_llm = FakeLLMClient(configured=False)
        _add_agri_chunk(vector_store, "Nitrogen fertilizer promotes vegetative growth.")
        pipeline = _build_pipeline(vector_store, unconfigured_llm)
        pipeline.answer("nitrogen and crops")
        assert len(unconfigured_llm.calls) == 0


# ---------------------------------------------------------------------------
# LLM client tests
# ---------------------------------------------------------------------------
class TestLLMClient:
    def test_not_configured_error_when_no_key(self) -> None:
        from src.config import Settings
        from src.llm_client import LLMNotConfiguredError, OpenAICompatibleClient

        settings = Settings(
            data_raw_dir=Path("/tmp/raw"),
            data_processed_dir=Path("/tmp/proc"),
            chroma_path=Path("/tmp/chroma"),
            collection_name="test",
            llm_api_key=None,
            llm_model="gpt-4o-mini",
        )
        client = OpenAICompatibleClient(settings)
        assert not client.is_configured
        with pytest.raises(LLMNotConfiguredError, match="LLM_API_KEY"):
            client.generate("hello")

    def test_fake_llm_records_calls(self) -> None:
        from src.llm_client import FakeLLMClient

        llm = FakeLLMClient(response="test-answer")
        answer = llm.generate("my prompt", system="my system")
        assert answer == "test-answer"
        assert len(llm.calls) == 1
        assert llm.calls[0]["prompt"] == "my prompt"
        assert llm.calls[0]["system"] == "my system"

    def test_fake_llm_is_configured(self) -> None:
        from src.llm_client import FakeLLMClient

        assert FakeLLMClient().is_configured is True

    def test_unknown_provider_raises(self) -> None:
        from src.config import Settings
        from src.llm_client import LLMNotConfiguredError, build_llm_client

        settings = Settings(
            data_raw_dir=Path("/tmp/raw"),
            data_processed_dir=Path("/tmp/proc"),
            chroma_path=Path("/tmp/chroma"),
            collection_name="test",
            llm_provider="unknown_provider",
            llm_api_key="key",
            llm_model="model",
        )
        with pytest.raises(LLMNotConfiguredError, match="unknown_provider"):
            build_llm_client(settings)


# ---------------------------------------------------------------------------
# Optional ML context
# ---------------------------------------------------------------------------
class TestMLContext:
    def test_ml_results_none_works_without_error(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Rice requires standing water during early growth.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("rice cultivation", ml_results=None)
        assert result.ml_context_provided is False
        assert result.llm_used is True

    def test_ml_results_surfaced_in_prompt(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Wheat does well in well-drained loamy soil.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        ml = {"predicted_crop": "wheat", "fertilizer_recommendation": None}
        result = pipeline.answer("soil management", ml_results=ml)
        assert result.ml_context_provided is True
        # The LLM call's prompt should include the non-null field.
        assert len(fake_llm.calls) == 1
        assert "wheat" in fake_llm.calls[0]["prompt"].lower()

    def test_null_ml_fields_not_included_in_prompt(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Maize grows best in warm climates.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        ml = {"predicted_crop": "maize", "yield_prediction": None, "fertilizer_recommendation": None}
        pipeline.answer("crop growing conditions", ml_results=ml)
        prompt = fake_llm.calls[0]["prompt"]
        # yield_prediction and fertilizer_recommendation are null → not in prompt.
        assert "yield_prediction" not in prompt
        assert "fertilizer_recommendation" not in prompt
        # predicted_crop is non-null → must be present.
        assert "maize" in prompt.lower()

    def test_ml_results_not_modified(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Groundnut needs light sandy soil.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        ml = {"predicted_crop": "groundnut", "some_other": "value"}
        original = copy.deepcopy(ml)
        pipeline.answer("soil for groundnut", ml_results=ml)
        assert ml == original  # pipeline must not mutate caller's dict

    def test_ml_wrong_type_ignored_with_warning(self, vector_store, fake_llm):
        pytest.importorskip("chromadb")
        _add_agri_chunk(vector_store, "Sugarcane requires a tropical climate.")
        pipeline = _build_pipeline(vector_store, fake_llm)
        result = pipeline.answer("sugarcane growing", ml_results=["not", "a", "dict"])
        assert result.ml_context_provided is False
        assert any("ml_results" in w.lower() or "dict" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Source formatter
# ---------------------------------------------------------------------------
class TestSourceFormatter:
    def _make_items(self, n: int = 2):
        from src.vector_store import RetrievedItem

        return [
            RetrievedItem(
                text=f"Passage {i} about crop irrigation practices.",
                metadata={"source": f"guide_{i}.pdf", "page": i},
                similarity=0.9 - i * 0.1,
                chunk_id=f"chunk_{i}",
            )
            for i in range(1, n + 1)
        ]

    def test_context_block_contains_reference_numbers(self) -> None:
        from src.source_formatter import format_context_block

        items = self._make_items(2)
        block = format_context_block(items)
        assert "[1]" in block
        assert "[2]" in block

    def test_context_block_contains_source_and_page(self) -> None:
        from src.source_formatter import format_context_block

        items = self._make_items(1)
        block = format_context_block(items)
        assert "guide_1.pdf" in block
        assert "p. 1" in block

    def test_empty_items_returns_no_results_message(self) -> None:
        from src.source_formatter import format_context_block

        block = format_context_block([])
        assert "no relevant" in block.lower() or "not found" in block.lower()

    def test_citation_legend_lists_all_sources(self) -> None:
        from src.source_formatter import format_citation_legend

        items = self._make_items(3)
        legend = format_citation_legend(items)
        assert "Sources used:" in legend
        assert "[1]" in legend and "[2]" in legend and "[3]" in legend
        assert "guide_1.pdf" in legend

    def test_citation_legend_empty_for_no_items(self) -> None:
        from src.source_formatter import format_citation_legend

        assert format_citation_legend([]) == ""

    def test_no_evidence_warning_is_visible(self) -> None:
        from src.source_formatter import format_no_evidence_warning

        warning = format_no_evidence_warning("Not enough information.")
        assert "INSUFFICIENT EVIDENCE" in warning
        assert "Not enough information." in warning

    def test_display_format_shows_similarity(self) -> None:
        from src.source_formatter import format_sources_for_display

        items = self._make_items(1)
        display = format_sources_for_display(items, show_score=True)
        assert "similarity" in display.lower()

    def test_display_format_no_score_flag(self) -> None:
        from src.source_formatter import format_sources_for_display

        items = self._make_items(1)
        display = format_sources_for_display(items, show_score=False)
        assert "similarity" not in display.lower()
