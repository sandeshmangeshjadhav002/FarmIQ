"""Tests for document_loader.py.

Coverage
--------
* TXT extraction — normal, empty, non-existent, unsupported extension.
* PDF extraction — multi-page, empty page skipping, missing file.
* Metadata contract — source, source_path, page, file_type.
* load_directory — multiple files, recursive discovery, no-files-found warning.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.document_loader import Document, load_directory, load_document


# ---------------------------------------------------------------------------
# TXT loading
# ---------------------------------------------------------------------------
class TestLoadTxt:
    def test_normal_txt(self, tmp_path: Path) -> None:
        f = tmp_path / "soil_health.txt"
        f.write_text("Good soil organic matter is essential for crop growth.", encoding="utf-8")
        docs = load_document(f)
        assert len(docs) == 1
        doc = docs[0]
        assert "soil organic matter" in doc.text
        assert doc.metadata["source"] == "soil_health.txt"
        assert doc.metadata["file_type"] == "txt"
        assert doc.page == 1

    def test_metadata_source_path_is_absolute(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("content", encoding="utf-8")
        docs = load_document(f)
        assert Path(docs[0].metadata["source_path"]).is_absolute()  # type: ignore[arg-type]

    def test_empty_txt_returns_empty_list(self, tmp_path: Path, caplog) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("   \n\n  ", encoding="utf-8")
        docs = load_document(f)
        assert docs == []
        assert any("empty" in msg.lower() or "skip" in msg.lower() for msg in caplog.messages)

    def test_nonexistent_file_returns_empty_list(self, tmp_path: Path, caplog) -> None:
        docs = load_document(tmp_path / "ghost.txt")
        assert docs == []
        assert any("not exist" in m.lower() or "does not" in m.lower() for m in caplog.messages)

    def test_unsupported_extension_returns_empty_list(self, tmp_path: Path, caplog) -> None:
        f = tmp_path / "data.csv"
        f.write_text("col1,col2\na,b\n", encoding="utf-8")
        docs = load_document(f)
        assert docs == []

    def test_md_extension_supported(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# Irrigation Guide\nWater deeply once a week.", encoding="utf-8")
        docs = load_document(f)
        assert len(docs) == 1
        assert docs[0].metadata["file_type"] == "txt"


# ---------------------------------------------------------------------------
# PDF loading
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_pdf(tmp_path: Path):
    """Create a real two-page PDF; skip the test class if PyMuPDF is absent."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "crop_guide.pdf"
    doc = pymupdf.open()
    for text in ["Irrigation is the supply of water to crops.", "Drip irrigation saves up to 50% water."]:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestLoadPdf:
    def test_pages_become_separate_documents(self, sample_pdf: Path) -> None:
        docs = load_document(sample_pdf)
        assert len(docs) == 2

    def test_page_numbers_are_1_indexed(self, sample_pdf: Path) -> None:
        docs = load_document(sample_pdf)
        pages = [d.page for d in docs]
        assert pages == [1, 2]

    def test_source_metadata(self, sample_pdf: Path) -> None:
        docs = load_document(sample_pdf)
        assert all(d.metadata["source"] == "crop_guide.pdf" for d in docs)
        assert all(d.metadata["file_type"] == "pdf" for d in docs)

    def test_text_extracted(self, sample_pdf: Path) -> None:
        docs = load_document(sample_pdf)
        combined = " ".join(d.text for d in docs)
        assert "Irrigation" in combined

    def test_missing_pdf_returns_empty_list(self, tmp_path: Path, caplog) -> None:
        docs = load_document(tmp_path / "missing.pdf")
        assert docs == []


# ---------------------------------------------------------------------------
# load_directory
# ---------------------------------------------------------------------------
class TestLoadDirectory:
    def test_discovers_multiple_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("Crop rotation improves soil health.", encoding="utf-8")
        (tmp_path / "b.txt").write_text("Fertilizer application timing is critical.", encoding="utf-8")
        docs = load_directory(tmp_path)
        sources = {d.metadata["source"] for d in docs}
        assert sources == {"a.txt", "b.txt"}

    def test_empty_directory_warns(self, tmp_path: Path, caplog) -> None:
        docs = load_directory(tmp_path)
        assert docs == []
        assert any("no supported" in m.lower() or "not found" in m.lower() for m in caplog.messages)

    def test_nonexistent_directory_warns(self, tmp_path: Path, caplog) -> None:
        docs = load_directory(tmp_path / "does_not_exist")
        assert docs == []

    def test_recursive_discovery(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("Pest management in rice.", encoding="utf-8")
        docs = load_directory(tmp_path)
        sources = [d.metadata["source"] for d in docs]
        assert "nested.txt" in sources

    def test_document_dataclass_properties(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("some content", encoding="utf-8")
        docs = load_directory(tmp_path)
        assert len(docs) == 1
        d = docs[0]
        assert isinstance(d, Document)
        assert d.source == "test.txt"
        assert d.page == 1
