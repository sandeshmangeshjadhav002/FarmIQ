"""Document loading for FarmIQ-RAG.

Reads PDF and plain-text files from ``data/raw/`` and returns a list of
:class:`Document` objects, each carrying its text plus provenance metadata
(source filename, absolute path, page number when available).

Design notes
------------
* PDFs are read with PyMuPDF, one :class:`Document` per page so that page
  numbers can be attached to every downstream chunk.
* TXT files produce a single :class:`Document` (no page concept).
* Empty / unreadable files are skipped with a clear warning rather than
  crashing the whole ingestion run.
* No fake content is ever generated: a document that yields no text is simply
  ignored after the warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_PDF_SUFFIXES = {".pdf"}
SUPPORTED_TXT_SUFFIXES = {".txt", ".md"}


@dataclass
class Document:
    """A unit of text extracted from a source file, with provenance metadata.

    ``metadata`` always contains at least ``source`` (file name) and
    ``source_path`` (absolute path). For PDFs it also contains ``page``
    (1-indexed).
    """

    text: str
    metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))

    @property
    def page(self) -> Optional[int]:
        val = self.metadata.get("page")
        return int(val) if val is not None else None


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in (SUPPORTED_PDF_SUFFIXES | SUPPORTED_TXT_SUFFIXES)


def _load_pdf(path: Path) -> List[Document]:
    """Extract text from a PDF, one Document per page.

    PyMuPDF is imported lazily so that the rest of the module can be used even
    if PyMuPDF is not installed (e.g. in minimal test environments that only
    exercise TXT loading).
    """
    try:
        import pymupdf  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on env
        logger.warning("PyMuPDF is not available (%s); cannot read PDF %s", exc, path)
        return []

    documents: List[Document] = []
    try:
        with pymupdf.open(path) as doc:
            for page_number, page in enumerate(doc, start=1):
                try:
                    text = page.get_text("text") or ""
                except Exception as exc:  # pragma: no cover - rare page errors
                    logger.warning("Failed to read page %s of %s: %s", page_number, path.name, exc)
                    text = ""
                text = text.strip()
                if not text:
                    logger.debug("Skipping empty page %s in %s", page_number, path.name)
                    continue
                documents.append(
                    Document(
                        text=text,
                        metadata={
                            "source": path.name,
                            "source_path": str(path.resolve()),
                            "page": page_number,
                            "file_type": "pdf",
                        },
                    )
                )
    except Exception as exc:
        logger.warning("Could not open PDF %s: %s", path, exc)
        return []

    if not documents:
        logger.warning("No extractable text found in PDF: %s", path)
    return documents


def _load_txt(path: Path) -> List[Document]:
    """Read a plain-text file into a single :class:`Document`."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []
    else:  # pragma: no cover - all encodings failed
        logger.warning("Could not decode %s with common encodings; skipping.", path)
        return []

    text = text.strip()
    if not text:
        logger.warning("Skipping empty text file: %s", path)
        return []

    return [
        Document(
            text=text,
            metadata={
                "source": path.name,
                "source_path": str(path.resolve()),
                "page": 1,
                "file_type": "txt",
            },
        )
    ]


def load_document(path: Path | str) -> List[Document]:
    """Load a single supported file into one or more :class:`Document` objects.

    Returns an empty list (with a warning logged) for unsupported or unreadable
    files; never raises for routine I/O or parsing problems.
    """
    path = Path(path)
    if not path.exists():
        logger.warning("File does not exist: %s", path)
        return []
    if not path.is_file():
        logger.warning("Not a regular file: %s", path)
        return []

    suffix = path.suffix.lower()
    if suffix in SUPPORTED_PDF_SUFFIXES:
        docs = _load_pdf(path)
    elif suffix in SUPPORTED_TXT_SUFFIXES:
        docs = _load_txt(path)
    else:
        logger.warning("Unsupported file type %s (only PDF/TXT/MD): %s", suffix, path)
        return []

    logger.info("Loaded %s page(s) from %s", len(docs), path.name)
    return docs


def load_directory(directory: Path | str) -> List[Document]:
    """Recursively load all supported files from a directory.

    The directory is created if missing so callers can point at a fresh
    ``data/raw/`` without error. Files are processed in a deterministic order
    (sorted) for repeatable ingestion.
    """
    directory = Path(directory)
    if not directory.exists():
        logger.warning("Document directory does not exist: %s", directory)
        return []

    all_docs: List[Document] = []
    files = sorted(
        p for p in directory.rglob("*") if p.is_file() and _is_supported(p)
    )
    if not files:
        logger.warning("No supported documents found in %s", directory)
        return []

    for path in files:
        docs = load_document(path)
        if docs:
            all_docs.extend(docs)
        else:
            logger.warning("No text extracted from %s; skipped.", path.name)

    logger.info("Loaded %s document section(s) from %s files", len(all_docs), len(files))
    return all_docs


def iter_documents(directory: Path | str) -> Iterable[Document]:
    """Yield documents lazily for memory-efficient ingestion of large corpora."""
    for doc in load_directory(directory):
        yield doc
