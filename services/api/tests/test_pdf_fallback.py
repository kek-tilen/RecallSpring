"""PDFs pypdf cannot open (e.g. AES-protected lecture slides without the cryptography package) are read with PDFium."""

from __future__ import annotations

from pathlib import Path

import pypdf
import pytest

from recallspring_api.ingest.extract import extract_pdf

from .pdfs import make_pdf


def test_pdfium_reads_what_pypdf_cannot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "slides.pdf"
    path.write_bytes(make_pdf(["Stevilski sistemi: osnova r = 2, 8, 10, 16.", "Boolova algebra in minimizacija."]))

    def refuse(*_a: object, **_k: object) -> None:
        raise pypdf.errors.DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(pypdf, "PdfReader", refuse)
    result = extract_pdf(path, max_pages=100)
    assert result.status == "ready" and "/pdfium-" in result.parser_version
    assert result.page_count == 2
    assert [s.citation_label for s in result.sections] == ["p. 1", "p. 2"]
    assert "Stevilski sistemi" in result.sections[0].text


def test_a_file_neither_parser_can_open_is_still_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nnot really a pdf")
    result = extract_pdf(path, max_pages=100)
    assert result.status == "failed" and result.error_code == "pdf_unreadable"
