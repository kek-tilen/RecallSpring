"""Word, PowerPoint and Excel sources: cited sections, honest gaps, and hostile packages refused."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import func, select

from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.ingest import office
from recallspring_api.ingest.extract import extract
from recallspring_api.ingest.jobs import run_pending
from recallspring_api.models import Source

from .conftest import Api
from .office import MC, docx, para, picture, pptx, shape, style, table, xlsx


def course(api: Api) -> str:
    return api.post("/courses", {"title": "Celična biologija"}).json()["id"]


def uploaded(api: Api, filename: str, content: bytes) -> tuple[dict, list[dict]]:
    created = api.upload(course(api), filename, content)
    assert created.status_code == 201, created.json()
    run_pending()
    source = api.get(f"/sources/{created.json()['id']}").json()
    return source, api.sections(source["id"])


def extracted(tmp_path: Path, kind: str, content: bytes, max_pages: int = 600) -> office.Result:
    path = tmp_path / f"file.{kind}"
    path.write_bytes(content)
    return extract(path, kind, max_pages)


TEXT_BOX = (
    f'<w:r><mc:AlternateContent xmlns:mc="{MC}"><mc:Choice Requires="wps"><w:drawing><w:txbxContent>'
    "<w:p><w:r><w:t>Okvir: ATP je energija</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>"
    "<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Okvir: ATP je energija</w:t></w:r></w:p></w:txbxContent>"
    "</w:pict></mc:Fallback></mc:AlternateContent></w:r>"
)


def test_word_headings_tables_lists_and_footnotes_become_cited_sections(owner_api: Api) -> None:
    styles = (
        style("Naslov1", "heading 1")  # Slovenian Word: localised style id, English built-in name
        + style("Naslov2", "heading 2")
        + style("Kazalo1", "toc 1")
        + style("Poglavje", "Poglavje", based_on="Naslov1")
    )
    body = (
        para("Univerza v Mariboru")
        + para("Uvod\t1", "Kazalo1")
        + para("Uvod", "Naslov1")
        + "<w:p><w:r><w:t>Celica je osnovna enota</w:t></w:r>"
        + "<w:del><w:r><w:delText> NAPAKA</w:delText></w:r></w:del>"
        + '<w:ins><w:r><w:t xml:space="preserve"> življenja.</w:t></w:r></w:ins>'
        + '<w:r><w:footnoteReference w:id="2"/></w:r></w:p>'
        + para(extra=TEXT_BOX)
        + para("Mitohondrij", "Naslov2")
        + "<w:tbl><w:tr><w:tc>"
        + para("Organel")
        + "</w:tc><w:tc>"
        + para("Naloga")
        + "</w:tc></w:tr>"
        + "<w:tr><w:tc>"
        + para("Mitohondrij")
        + "</w:tc><w:tc>"
        + para("ATP")
        + "</w:tc></w:tr></w:tbl>"
        + para("prvi korak", num=True)
        + para("drugi korak", num=True)
        + para("Zaključek", "Poglavje")
        + para("Konec poglavja.")
    )
    footnotes = '<w:footnote w:id="2"><w:p><w:r><w:t>Vir: učbenik, str. 5.</w:t></w:r></w:p></w:footnote>'
    source, sections = uploaded(owner_api, "Predavanje 1.docx", docx(body, styles, footnotes))

    assert source["kind"] == "docx" and source["parse_state"] == "ready" and source["parse_message"] is None
    assert [s["citation_label"] for s in sections] == [
        "§ Start of document",
        "§ Uvod",
        "§ Mitohondrij",
        "§ Zaključek",
        "§ Notes",
    ]
    by_label = {s["citation_label"]: s for s in sections}
    intro = by_label["§ Uvod"]["text"]
    assert "Celica je osnovna enota življenja.[^1]" in intro and "NAPAKA" not in intro
    assert intro.count("Okvir: ATP je energija") == 1  # the drawing's fallback copy is not read twice
    assert by_label["§ Mitohondrij"]["heading"] == "Uvod › Mitohondrij"
    assert "Organel | Naloga\nMitohondrij | ATP" in by_label["§ Mitohondrij"]["text"]
    assert "- prvi korak\n- drugi korak" in by_label["§ Mitohondrij"]["text"]
    assert by_label["§ Notes"]["text"].endswith("[^1]: Vir: učbenik, str. 5.")
    assert all("Uvod\t1" not in s["text"] for s in sections)  # table of contents skipped
    assert [s["char_start"] for s in sections] == sorted(s["char_start"] for s in sections)


def test_word_without_headings_uses_numbered_parts_and_reports_pictures(tmp_path: Path) -> None:
    result = extracted(tmp_path, "docx", docx(para("Prvi odstavek.") + para("Drugi odstavek."), pictures=2))
    assert result.status == "ready"
    assert [(s.citation_label, s.text) for s in result.sections] == [("Part 1", "Prvi odstavek.\n\nDrugi odstavek.")]
    assert result.notes == ["pictures_not_extracted:2"]


def test_word_with_only_pictures_fails_honestly(owner_api: Api) -> None:
    source, sections = uploaded(owner_api, "scan.docx", docx(para(), pictures=1))
    assert source["parse_state"] == "failed" and source["parse_error"] == "no_extractable_text"
    assert source["parse_message"] == (
        "This document has no text or pictures RecallSpring can read. Export it as PDF: Claude can look at its pages."
    )
    assert sections == []


def test_slides_follow_presentation_order_with_titles_notes_tables_and_smartart(owner_api: Api) -> None:
    slides = [
        # file slide1.xml is shown second; slide2.xml first
        shape(["Dihalna veriga"], "title")
        + shape(["Kompleksi I–IV", ("prenos elektronov", 1)], "body")
        + shape(["Biologija 2026"], "ftr")
        + shape(["12"], "sldNum"),
        shape(["Celično dihanje"], "ctrTitle")
        + shape(["Pregled poglavja"])
        + f"<p:grpSp>{shape(['V skupini'])}</p:grpSp>",
        "HIDDEN:" + shape(["Dodatno"], "title") + table([["Faza", "Mesto"], ["Glikoliza", "citoplazma"]]),
    ]
    content = pptx(
        slides, order=[2, 1, 3], notes={1: "Povej primer cianida."}, smartart={2: ["Glikoliza", "Krebsov cikel"]}
    )
    source, sections = uploaded(owner_api, "Predavanje 3.pptx", content)

    assert source["kind"] == "pptx" and source["parse_state"] == "ready" and source["page_count"] == 3
    assert [(s["citation_label"], s["page"], s["heading"]) for s in sections] == [
        ("slide 1", 1, "Celično dihanje"),
        ("slide 2", 2, "Dihalna veriga"),
        ("slide 3", 3, "Dodatno (hidden slide)"),
    ]
    first, second, third = (s["text"] for s in sections)
    assert first.startswith("# Celično dihanje") and "V skupini" in first and "Krebsov cikel" in first
    assert "Kompleksi I–IV\n  prenos elektronov" in second
    assert second.endswith("Speaker notes:\nPovej primer cianida.")
    assert "Biologija 2026" not in second and "12" not in second and "Slide image" not in second
    assert "Faza | Mesto\nGlikoliza | citoplazma" in third


def test_picture_only_slides_need_attention_and_are_named(owner_api: Api) -> None:
    content = pptx([shape(["Uvod v celično biologijo"], "title"), picture(), shape(["Hvala"]) + picture()])
    source, sections = uploaded(owner_api, "slike.pptx", content)
    assert source["parse_state"] == "needs_attention"
    assert (
        source["parse_message"]
        == "Many slides have little or no text: 2, 3. Claude can look at the pictures on them on request."
    )
    assert [s["citation_label"] for s in sections] == ["slide 1", "slide 3"]  # nothing is invented for slide 2


def test_slide_limit_uses_the_page_limit(tmp_path: Path) -> None:
    result = extracted(tmp_path, "pptx", pptx([shape(["a"]), shape(["b"]), shape(["c"])]), max_pages=2)
    assert result.status == "failed" and result.error_code == "too_many_pages" and result.page_count == 3


SHEET_STYLES = (
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="d.m.yyyy"/></numFmts>'
    '<cellXfs count="4"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/><xf numFmtId="20"/></cellXfs>'
)


def test_spreadsheet_rows_keep_columns_values_and_dates(owner_api: Api) -> None:
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="D1" t="inlineStr"><is><t>Opomba</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>4.5</v></c><c r="C2" s="1"><v>45658</v></c>'
        '<c r="D2" t="b"><v>1</v></c></row>'
        '<row r="4"><c r="A4" t="str"><f>CONCAT("A","B")</f><v>AB</v></c><c r="B4"><f>B2*2</f><v>9</v></c>'
        '<c r="C4" s="2"><v>45659.5</v></c><c r="D4" s="3"><v>0.75</v></c><c r="E4" t="e"><v>#DIV/0!</v></c>'
        '<c r="F4"><f>SUM(B2:B4)</f></c></row>'  # saved without a computed result
    )
    shared = ["Ime", "Ocena", "<r><t>Ana</t></r><rPh><t>ana-phonetic</t></rPh>"]
    content = xlsx(
        [("Ocene", "visible", rows), ("Skrito", "hidden", '<row r="1"><c r="A1"><v>1</v></c></row>')],
        shared,
        SHEET_STYLES,
    )
    source, sections = uploaded(owner_api, "ocene.xlsx", content)

    assert source["kind"] == "xlsx" and source["parse_state"] == "ready" and "hidden_sheets:1" in source["parse_notes"]
    assert [(s["citation_label"], s["heading"]) for s in sections] == [("Ocene, rows 1–4", "Ocene")]
    assert sections[0]["text"].split("\n") == [
        "Row 1: Ime | Ocena |  | Opomba",
        "Row 2: Ana | 4.5 | 2025-01-01 | TRUE",
        "Row 4: AB | 9 | 2025-01-02 12:00 | 18:00 | #DIV/0! | =SUM(B2:B4)",
    ]


def test_long_sheets_split_and_repeat_the_header_row(tmp_path: Path) -> None:
    rows = (
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Pojem</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Razlaga</t></is></c></row>'
    )
    rows += "".join(
        f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>pojem {n}</t></is></c>'
        f'<c r="B{n}" t="inlineStr"><is><t>{"razlaga " * 6}</t></is></c></row>'
        for n in range(2, 302)
    )
    result = extracted(tmp_path, "xlsx", xlsx([("Slovar", "visible", rows)]))
    assert result.status == "ready" and len(result.sections) >= 3
    assert result.sections[0].citation_label.startswith("Slovar, rows 1–")
    assert result.sections[1].text.startswith("(columns as in Row 1: Pojem | Razlaga)\nRow ")
    assert result.sections[-1].citation_label.endswith("–301")
    assert all(len(s.text) <= 6100 for s in result.sections)


@pytest.mark.parametrize(
    ("code", "fmt_id", "fmt"),
    [
        ("date", 164, "d.m.yyyy"),
        ("date", 165, "[$-F800]dddd, mmmm dd, yyyy"),
        ("time", 166, "[h]:mm:ss"),
        (None, 167, '#,##0.00 "€"'),
        (None, 168, "_-* #,##0.00\\ _€_-;-* #,##0.00\\ _€_-"),
        (None, 169, "0.00E+00"),
        (None, 170, "General"),
        ("date", 14, None),
        (None, 2, None),
    ],
)
def test_excel_number_formats_are_recognised(code: str | None, fmt_id: int, fmt: str | None) -> None:
    assert office._format_kind(fmt_id, fmt) == code


# ---------------------------------------------------------------- refused and hostile files


def _source_count() -> int:
    with new_session() as db:
        return db.scalar(select(func.count()).select_from(Source)) or 0


def _zip(entries: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("slides.pptx", docx(para("Word, not PowerPoint")), 415, "content_does_not_match_type"),
        ("notes.docx", b"plain text pretending to be Word", 415, "content_does_not_match_type"),
        ("notes.docx", b"%PDF-1.4 renamed", 415, "content_does_not_match_type"),
        ("protected.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, 415, "office_protected"),
        ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, 415, "office_format_unsupported"),
        ("macros.xlsm", b"PK\x03\x04", 415, "office_format_unsupported"),
        ("broken.docx", b"PK\x03\x04 not really a zip", 415, "office_unreadable"),
        ("bare.docx", _zip({"word/document.xml": "<x/>"}), 415, "content_does_not_match_type"),
    ],
)
def test_upload_refuses_wrong_old_protected_or_broken_office_files(
    owner_api: Api, filename: str, content: bytes, status: int, code: str
) -> None:
    r = owner_api.upload(course(owner_api), filename, content)
    assert r.status_code == status and r.json()["code"] == code, r.json()
    assert _source_count() == 0


def test_xml_with_entity_declarations_is_never_parsed(owner_api: Api) -> None:
    bomb = '<!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    source, sections = uploaded(owner_api, "bomb.docx", docx(para("&b;"), prolog=bomb))
    assert source["parse_state"] == "failed" and source["parse_error"] == "unsafe_document" and sections == []


def test_oversized_parts_and_crowded_packages_fail_before_reading(
    owner_api: Api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(office, "MAX_PART_BYTES", 2_000)
    big = extracted(tmp_path, "docx", docx(para("x" * 5_000)))
    assert big.status == "failed" and big.error_code == "document_too_large"

    monkeypatch.setattr(office, "MAX_ENTRIES", 5)
    crowded = docx(para("text"), pictures=10)
    assert extracted(tmp_path, "docx", crowded).error_code == "document_too_large"
    r = owner_api.upload(course(owner_api), "crowded.docx", crowded)
    assert r.status_code == 413 and r.json()["code"] == "document_too_large"


def test_relationship_targets_cannot_leave_the_package() -> None:
    assert office._resolve("ppt", "slides/slide1.xml") == "ppt/slides/slide1.xml"
    assert office._resolve("ppt/slides", "../media/image%201.png") == "ppt/media/image 1.png"
    assert office._resolve("ppt/slides", "/ppt/notesSlides/n1.xml") == "ppt/notesSlides/n1.xml"
    assert office._resolve("word", "../../../etc/passwd") is None
    assert office._resolve("word", "") is None


def test_office_extraction_runs_in_the_isolated_process(owner_api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "extraction_isolation", "subprocess")
    body = para("Izolirano", "Heading1") + para("Prebrano v ločenem procesu.")
    source, sections = uploaded(owner_api, "izolirano.docx", docx(body, style("Heading1", "heading 1")))
    assert source["parse_state"] == "ready", source
    assert sections[0]["citation_label"] == "§ Izolirano" and "ločenem procesu" in sections[0]["text"]
