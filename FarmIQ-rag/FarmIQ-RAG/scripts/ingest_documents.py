#!/usr/bin/env python
"""FarmIQ-RAG document ingestion CLI.

Reads PDF/TXT/MD files from ``data/raw/``, splits them into overlapping chunks,
embeds them with the shared SentenceTransformer model, and upserts them into
the ChromaDB collection at ``CHROMA_PATH``.

Usage
-----
    # Ingest all supported documents in data/raw/ (idempotent: re-running
    # upserts identical content instead of duplicating it)
    python scripts/ingest_documents.py

    # Wipe and rebuild the index from scratch (removes orphaned chunks)
    python scripts/ingest_documents.py --rebuild

    # Point at a custom source directory
    python scripts/ingest_documents.py --data-dir /path/to/docs
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make ``src`` importable when running the script directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import get_settings  # noqa: E402
from src.document_loader import load_directory  # noqa: E402
from src.embeddings import build_embedder  # noqa: E402
from src.text_chunker import TextChunker  # noqa: E402
from src.vector_store import VectorStore  # noqa: E402

logger = logging.getLogger("farmiq_rag.ingest")


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest agricultural documents into the FarmIQ-RAG vector index.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing PDF/TXT/MD files (default: data/raw).",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and recreate the collection before ingesting (removes orphans).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Override CHUNK_SIZE for this run.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="Override CHUNK_OVERLAP for this run.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    settings.ensure_dirs()

    data_dir = args.data_dir or settings.data_raw_dir
    if not data_dir.exists():
        logger.error(
            "Source directory does not exist: %s\n"
            "Add PDF/TXT agricultural documents there and re-run, or pass --data-dir.",
            data_dir,
        )
        print(f"[ERROR] Source directory does not exist: {data_dir}")
        print("        Add PDF/TXT agricultural documents there and re-run.")
        return 2

    # ── Build components with the SAME embedder for ingestion and retrieval ──
    embedder = build_embedder(
        model_name=settings.embedding_model,
        cache_dir=str(settings.hf_cache_dir) if settings.hf_cache_dir else None,
    )
    vector_store = VectorStore(
        chroma_path=settings.chroma_path,
        collection_name=settings.collection_name,
        distance_metric=settings.distance_metric,
        embedder=embedder,
    )

    if args.rebuild:
        logger.info("Rebuilding index (--rebuild).")
        vector_store.rebuild()

    # ── Load documents ───────────────────────────────────────────────────────
    print(f"[INFO] Loading documents from {data_dir} ...")
    documents = load_directory(data_dir)
    if not documents:
        print(
            "[WARN] No readable documents found. Place trusted agricultural PDF/TXT "
            "files (ICAR, SAU, govt, FAO, ...) in the source directory and re-run."
        )
        print(f"[INFO] Index contains {vector_store.count()} chunk(s).")
        return 0

    total_sections = len(documents)
    print(f"[INFO] Loaded {total_sections} document section(s) from {len({d.source for d in documents})} file(s).")

    # ── Chunk ────────────────────────────────────────────────────────────────
    chunk_size = args.chunk_size if args.chunk_size is not None else settings.chunk_size
    chunk_overlap = args.chunk_overlap if args.chunk_overlap is not None else settings.chunk_overlap
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = chunker.split_documents(documents)
    if not chunks:
        print("[WARN] Text splitting produced no chunks. Check that documents contain extractable text.")
        return 0
    print(f"[INFO] Split into {len(chunks)} chunk(s) (size={chunk_size}, overlap={chunk_overlap}).")

    # ── Embed + store ────────────────────────────────────────────────────────
    print(f"[INFO] Embedding with model '{settings.embedding_model}' (first run may download weights) ...")
    added = vector_store.add_chunks(chunks)

    # ── Summary ──────────────────────────────────────────────────────────────
    final_count = vector_store.count()
    sources = vector_store.list_sources()
    print("[OK] Ingestion complete.")
    print(f"     Chunks upserted this run : {added}")
    print(f"     Total chunks in index    : {final_count}")
    print(f"     Unique source files       : {len(sources)}")
    if sources:
        preview = ", ".join(sorted(sources)[:10])
        more = "" if len(sources) <= 10 else f" ... (+{len(sources) - 10} more)"
        print(f"     Sources                  : {preview}{more}")
    print(f"     Collection               : {settings.collection_name}")
    print(f"     Chroma path              : {settings.chroma_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
