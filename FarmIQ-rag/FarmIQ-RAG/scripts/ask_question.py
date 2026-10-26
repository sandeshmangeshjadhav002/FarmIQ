#!/usr/bin/env python
"""FarmIQ-RAG question-answering CLI.

Asks the agricultural assistant a question and prints the generated answer,
the retrieved source passages (with page numbers when available), and a clear
warning when no relevant evidence is found.

Usage
-----
    python scripts/ask_question.py --question "How should I manage irrigation for a soybean crop?"

    # Optional: ground the answer in FarmIQ ML predictions (JSON)
    python scripts/ask_question.py \
        --question "What fertilizer schedule suits the recommended crop?" \
        --ml-results '{"predicted_crop": "soybean", "fertilizer_recommendation": "DAP"}'

    # Override retrieval parameters
    python scripts/ask_question.py --question "..." --top-k 8 --threshold 0.35
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make ``src`` importable when running the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import get_settings  # noqa: E402
from src.rag_pipeline import build_rag_pipeline  # noqa: E402
from src.retriever import RetrievalStatus  # noqa: E402
from src.source_formatter import (  # noqa: E402
    format_no_evidence_warning,
    format_sources_for_display,
)

logger = logging.getLogger("farmiq_rag.ask")


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask the FarmIQ-RAG agricultural assistant a question.",
    )
    parser.add_argument(
        "--question", "-q",
        required=True,
        help="The farmer's question (in English or a supported Indian language).",
    )
    parser.add_argument(
        "--ml-results",
        default=None,
        help=(
            "Optional JSON object of FarmIQ ML predictions, e.g. "
            "'{\"predicted_crop\": \"soybean\"}'. Missing/null fields are ignored."
        ),
    )
    parser.add_argument("--top-k", type=int, default=None, help="Override TOP_K.")
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Override RELEVANCE_THRESHOLD (min cosine similarity 0..1).",
    )
    parser.add_argument(
        "--no-sources", action="store_true",
        help="Do not print the retrieved source list (answer only).",
    )
    return parser.parse_args(argv)


def _parse_ml_results(raw: str | None):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] --ml-results is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("[ERROR] --ml-results must be a JSON object.")
    return data


def _print_result(result, *, show_sources: bool) -> None:
    print("\n" + "=" * 70)
    print("FarmIQ Agricultural Assistant")
    print("=" * 70)

    # Warnings first so the user sees context for degraded answers.
    if result.warnings:
        for w in result.warnings:
            print(f"[WARN] {w}")

    # Empty knowledge base / no relevant evidence: explicit, helpful message.
    if result.retrieval_status == RetrievalStatus.EMPTY_INDEX:
        print("\n" + format_no_evidence_warning(result.retrieval_message))
        print("\nNo answer was generated because the knowledge base is empty.")
        return

    if result.retrieval_status == RetrievalStatus.BELOW_THRESHOLD:
        print("\n" + format_no_evidence_warning(result.retrieval_message))
        print("\nAnswer:")
        print(result.answer or "(no answer)")
        if show_sources and result.sources:
            print("\nRetrieved sources:")
            print(format_sources_for_display(result.sources))
        return

    # Normal path: answer + sources.
    print("\nAnswer:")
    print(result.answer)

    if result.ml_context_provided and result.ml_context_summary:
        print("\nFarmIQ ML predictions used (model output, not verified facts):")
        print("  " + result.ml_context_summary.replace("\n", "\n  "))

    if show_sources:
        print("\nRetrieved sources:")
        print(format_sources_for_display(result.sources))

    used = "real LLM" if result.llm_used else "LLM not configured (passages only)"
    print(f"\n[INFO] LLM: {used} | sources: {len(result.sources)}")


def main(argv=None) -> int:
    args = _parse_args(argv)
    settings = get_settings()

    ml_results = _parse_ml_results(args.ml_results)

    print(f"[INFO] Embedding model: {settings.embedding_model}")
    print(f"[INFO] Collection     : {settings.collection_name}")
    print(f"[INFO] Chroma path    : {settings.chroma_path}")

    # Build the full pipeline (shared embedder ensures ingest==retrieve model).
    try:
        pipeline = build_rag_pipeline(settings)
    except Exception as exc:
        print(f"[ERROR] Failed to initialise pipeline: {exc}")
        return 2

    # Helpful early check for an empty index.
    try:
        if pipeline.retriever.vector_store.is_empty():
            print(
                "[WARN] The index is empty. Run ingestion first:\n"
                "       python scripts/ingest_documents.py"
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Index check failed: %s", exc)

    if not settings.llm_configured:
        print(
            "[WARN] LLM_API_KEY is not set. Retrieval will run, but answers will be "
            "raw passages only. Configure LLM_API_KEY and LLM_MODEL in .env to generate "
            "full answers."
        )

    try:
        result = pipeline.answer(
            question=args.question,
            ml_results=ml_results,
            top_k=args.top_k,
            relevance_threshold=args.threshold,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to answer question: {exc}")
        return 1

    _print_result(result, show_sources=not args.no_sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
