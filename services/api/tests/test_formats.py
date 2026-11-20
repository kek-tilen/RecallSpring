"""More source formats: OpenDocument, CSV/TSV, subtitles, notebooks, code and LaTeX become cited sections."""

from __future__ import annotations

import base64
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest

from recallspring_api.ingest.jobs import run_pending

from .conftest import Api
from .odf import (
    ENCRYPTED_MANIFEST,
    HIDDEN_TABLE_STYLE,
    cell,
    h,
    image_frame,
    p,
    package,
    row,
    sheet,
    slide,
    text_frame,
)
from .office import PNG_1PX

_COURSES = itertools.count(1)


def course(api: Api) -> str:
    return api.post("/courses", {"title": f"Podatkovne baze {next(_COURSES)}"}).json()["id"]


def uploaded(api: Api, filename: str, content: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    created = api.upload(course(api), filename, content)
    assert created.status_code == 201, created.json()
    run_pending()
    source = api.get(f"/sources/{created.json()['id']}").json()
    return source, api.sections(source["id"])


# ---------------------------------------------------------------- OpenDocument


def test_odt_headings_lists_tables_and_pictures_without_comments_or_deletions(owner_api: Api) -> None:
    body = (
        "<text:tracked-changes><text:changed-region><text:deletion><text:p>Izbrisano besedilo</text:p>"
        "</text:deletion></text:changed-region></text:tracked-changes>"
        "<text:table-of-content><text:index-body><text:p>Uvod 1</text:p></text:index-body></text:table-of-content>"
        + h("Uvod")
        + p("Relacijski model <text:span>temelji</text:span> na<text:s/>relacijah.")
        + p("Komentar", "<office:annotation><text:p>Moj komentar</text:p></office:annotation>")
        + "<text:list><text:list-item>"
        + p("Primarni ključ")
        + "</text:list-item><text:list-item>"
        + p("Tuji ključ")
        + "</text:list-item></text:list>"
        + h("Normalizacija", 2)
        + '<table:table table:name="T1"><table:table-row>'
        + cell("Oblika")
        + cell("Pogoj")
        + "</table:table-row><table:table-row>"
        + cell("1NF")
        + cell("atomarne vrednosti")
        + "</table:table-row></table:table>"
        + p("Shema:", image_frame("Pictures/er.png", "ER diagram"))
        + p(
            "Opomba",
            "<text:note><text:note-citation>1</text:note-citation><text:note-body>"
            + p("Codd, 1970")
            + "</text:note-body></text:note>",
        )
    )
    content = package("odt", body, files={"Pictures/er.png": PNG_1PX})
    source, sections = uploaded(owner_api, "zapiski.odt", content)
    assert source["kind"] == "odt" and source["parse_state"] == "ready", source
    assert [s["citation_label"] for s in sections] == ["§ Uvod", "§ Normalizacija"]
    first, second = sections[0]["text"], sections[1]["text"]
    assert "Relacijski model temelji na relacijah." in first and "- Primarni ključ" in first
    assert "Izbrisano" not in first and "Moj komentar" not in first and "Uvod 1" not in first
    assert "Oblika | Pogoj\n1NF | atomarne vrednosti" in second
    assert "Shema: [picture 1: ER diagram]" in second and "Opomba [note: Codd, 1970]" in second
    assert source["parse_notes"] == ["pictures_not_extracted:1"]


def test_odp_slides_with_titles_pictures_and_speaker_notes(owner_api: Api) -> None:
    slides = (
        slide(
            text_frame(p("Indeksi"), "title") + text_frame(p("B-drevo") + p("Zgoščevanje"), "outline"),
            notes="Povej primer s telefonskim imenikom.",
        )
        + slide(image_frame("Pictures/graf.png", "Graf časa iskanja"))
        + slide(text_frame(p("Vprašanja?"), "title"))
    )
    content = package("odp", slides, files={"Pictures/graf.png": PNG_1PX})
    source, sections = uploaded(owner_api, "predavanje.odp", content)
    assert source["kind"] == "odp" and source["page_count"] == 3
    assert [s["citation_label"] for s in sections] == ["slide 1", "slide 2", "slide 3"]
    assert sections[0]["text"] == (
        "# Indeksi\n\nB-drevo\nZgoščevanje\n\nSpeaker notes:\nPovej primer s telefonskim imenikom."
    )
    assert sections[1]["text"] == "[picture 1: Graf časa iskanja]"
    assert "slides_without_text:2,3" in source["parse_notes"]


def test_ods_sheets_skip_hidden_ones_and_expand_repeats_within_bounds(owner_api: Api) -> None:
    sheets = sheet(
        "Ocene",
        row(cell("Ime") + cell("Točke"))
        + row(cell("Ana") + cell("42"))
        + row(cell(), repeat=5)
        + row(cell("Bor") + cell("", repeat=3) + cell("38"))
        + row(cell("x", repeat=2), repeat=3)
        + row(cell(), repeat=1_048_000),
    ) + sheet("Skrito", row(cell("geslo")), "ta2")
    content = package("ods", sheets, styles=HIDDEN_TABLE_STYLE)
    source, sections = uploaded(owner_api, "ocene.ods", content)
    assert source["kind"] == "ods" and source["parse_notes"] == ["hidden_sheets:1"]
    [section] = sections
    assert section["citation_label"] == "Ocene, rows 1–11"
    assert section["text"].split("\n") == [
        "Row 1: Ime | Točke",
        "Row 2: Ana | 42",
        "Row 8: Bor |  |  |  | 38",
        "Row 9: x | x",
        "Row 10: x | x",
        "Row 11: x | x",
    ]
    assert "geslo" not in section["text"]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (package("odt", p("Skrivno"), manifest=ENCRYPTED_MANIFEST), "office_protected"),
        (
            package("odt", p("Besedilo"), mimetype="application/vnd.oasis.opendocument.spreadsheet"),
            "content_does_not_match_type",
        ),
    ],
)
def test_protected_or_mislabelled_opendocument_is_refused(owner_api: Api, content: bytes, code: str) -> None:
    r = owner_api.upload(course(owner_api), "dokument.odt", content)
    assert r.status_code in (413, 415) and r.json()["code"] == code


# ---------------------------------------------------------------- CSV / TSV


def test_csv_from_slovenian_excel_is_read_as_windows_1250_and_said_so(owner_api: Api) -> None:
    content = 'Ime;Priimek;Ocena\nČrt;Šuštar;9\n"Žana";"Novak; ml.";10\n'.encode("cp1250")
    source, sections = uploaded(owner_api, "ocene.csv", content)
    assert source["kind"] == "csv" and source["parse_state"] == "ready" and source["page_count"] == 3
    assert source["parse_notes"] == ["decoded_as:windows-1250"]
    assert sections[0]["citation_label"] == "rows 1–3"
    assert sections[0]["text"] == "Row 1: Ime | Priimek | Ocena\nRow 2: Črt | Šuštar | 9\nRow 3: Žana | Novak; ml. | 10"


def test_tsv_uses_tabs_and_long_tables_repeat_the_header_reference(owner_api: Api) -> None:
    lines = ["id\tukaz"] + [f"{i}\tSELECT * FROM tabela_{i} WHERE stolpec = {i};" for i in range(1, 400)]
    source, sections = uploaded(owner_api, "ukazi.tsv", "\n".join(lines).encode())
    assert len(sections) > 1 and sections[1]["text"].startswith("(columns as in Row 1: id | ukaz)")
    assert sections[0]["text"].split("\n")[1] == "Row 2: 1 | SELECT * FROM tabela_1 WHERE stolpec = 1;"


# ---------------------------------------------------------------- subtitles

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>Dobrodošli</i> na predavanju.

2
00:00:03,600 --> 00:00:06,000
{\\an8}Danes: transakcije &amp; ACID.

3
00:00:12,000 --> 00:00:14,000
Atomarnost pomeni vse ali nič.

4
00:06:00,000 --> 00:06:04,000
Izolacija prepreči umazana branja.
"""

VTT = """WEBVTT

NOTE posneto v predavalnici P1

00:00.000 --> 00:02.000 align:start
<v Profesor>Kaj je indeks?

00:02.000 --> 00:04.000
<v Profesor>Kaj je indeks?
<v Študent>Struktura za hitro iskanje.
"""


def test_srt_subtitles_become_timed_paragraphs_in_five_minute_sections(owner_api: Api) -> None:
    source, sections = uploaded(owner_api, "predavanje.srt", SRT.encode())
    assert source["kind"] == "subtitles" and source["parse_state"] == "ready"
    assert [s["citation_label"] for s in sections] == ["00:01–00:14", "06:00–06:04"]
    assert sections[0]["text"] == (
        "[00:01] Dobrodošli na predavanju. Danes: transakcije & ACID.\n\n[00:12] Atomarnost pomeni vse ali nič."
    )


def test_vtt_keeps_speakers_and_drops_repeated_rolling_lines(owner_api: Api) -> None:
    _, sections = uploaded(owner_api, "posnetek.vtt", VTT.encode())
    assert sections[0]["text"] == "[00:00] Profesor: Kaj je indeks?\n\n[00:02] Študent: Struktura za hitro iskanje."


def test_file_without_cues_is_explained(owner_api: Api) -> None:
    source, _ = uploaded(owner_api, "prazno.srt", b"to ni podnapis\n")
    assert source["parse_state"] == "failed" and source["parse_error"] == "no_subtitle_cues"
    assert "srt" in source["parse_message"]


# ---------------------------------------------------------------- notebooks


def notebook(cells: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"language": "python"}}, "cells": cells}
    ).encode()


NOTEBOOK = notebook(
    [
        {"cell_type": "markdown", "source": ["# Regresija\n", "Najprej podatki."]},
        {
            "cell_type": "code",
            "execution_count": 1,
            "source": "import pandas as pd\ndf = pd.read_csv('a.csv')\ndf.head()",
            "outputs": [
                {"output_type": "stream", "name": "stdout", "text": ["prebrano 100 vrstic\n"]},
                {
                    "output_type": "execute_result",
                    "data": {"text/plain": ["   x  y\n0  1  2"], "text/html": ["<table><script>x</script></table>"]},
                },
            ],
        },
        {"cell_type": "markdown", "source": "## Graf"},
        {
            "cell_type": "code",
            "source": "df.plot()",
            "outputs": [
                {"output_type": "display_data", "data": {"image/png": base64.b64encode(PNG_1PX).decode()}},
                {
                    "output_type": "error",
                    "ename": "KeyError",
                    "evalue": "'z'",
                    "traceback": ["\x1b[0;31mKeyError\x1b[0m: 'z'"],
                },
            ],
        },
    ]
)


def test_notebook_cells_outputs_and_pictures_without_html(owner_api: Api) -> None:
    source, sections = uploaded(owner_api, "regresija.ipynb", NOTEBOOK)
    assert source["kind"] == "notebook" and source["page_count"] == 4
    assert [s["citation_label"] for s in sections] == ["§ Regresija", "§ Graf"]
    first, second = sections[0]["text"], sections[1]["text"]
    assert "```python\nimport pandas as pd" in first and "Output:\nprebrano 100 vrstic" in first
    assert "Output:\n   x  y\n0  1  2" in first and "<table>" not in first and "script" not in first
    assert "[picture 1]" in second and "KeyError: 'z'" in second and "\x1b" not in second


def test_broken_notebook_is_refused_or_explained(owner_api: Api) -> None:
    r = owner_api.upload(course(owner_api), "pokvarjen.ipynb", b"not json at all")
    assert r.status_code == 415 and r.json()["code"] == "content_does_not_match_type"
    source, _ = uploaded(owner_api, "pokvarjen2.ipynb", b'{"cells": "no"}')
    assert source["parse_error"] == "notebook_unreadable"


# ---------------------------------------------------------------- code and LaTeX


def test_code_keeps_indentation_and_line_numbers_and_names_the_language(owner_api: Api) -> None:
    functions = [f"def f{i}(x):\n    '''Funkcija {i}.'''\n    return x * {i}\n" for i in range(120)]
    code = "\n".join(functions)
    source, sections = uploaded(owner_api, "funkcije.py", code.encode())
    assert source["kind"] == "code" and source["page_count"] == len(code.rstrip("\n").split("\n"))
    assert len(sections) > 1 and all(s["heading"] == "Python code" for s in sections)
    assert sections[0]["citation_label"].startswith("lines 1–")
    assert sections[0]["text"].startswith("def f0(x):\n    '''Funkcija 0.'''\n    return x * 0")
    end = int(sections[0]["citation_label"].split("–")[1])
    assert sections[1]["citation_label"].startswith(f"lines {end + 1}–")
    assert all(not s["text"].endswith("def") for s in sections)


def test_binary_file_named_as_code_is_refused(owner_api: Api) -> None:
    r = owner_api.upload(course(owner_api), "program.c", b"\x7fELF\x02\x01\x01\x00\x00\x00")
    assert r.status_code == 415 and r.json()["code"] == "unsupported_encoding"


LATEX = r"""\documentclass{article}
\usepackage{amsmath}
\newcommand{\R}{\mathbb{R}} % realna števila
\title{Linearna algebra}
\begin{document}
\maketitle
\section{Vektorski prostori}
Prostor $\R^n$ je vektorski prostor. % to je komentar
% cela vrstica komentarja
Popust je 50\% cene.
\subsection*{Baza}
Baza je linearno neodvisna množica.
\begin{verbatim}
% to ostane
\end{verbatim}
\input{poglavje2}
\end{document}
"""


def test_latex_is_split_by_sections_without_comments_and_keeps_macros(owner_api: Api) -> None:
    source, sections = uploaded(owner_api, "algebra.tex", LATEX.encode())
    assert source["kind"] == "latex" and source["parse_notes"] == ["includes_not_resolved:1"]
    labels = [s["citation_label"] for s in sections]
    assert labels == ["§ Preamble (macros and title)", "§ Introduction", "§ Vektorski prostori", "§ Baza"]
    assert sections[0]["text"] == "\\newcommand{\\R}{\\mathbb{R}}\n\\title{Linearna algebra}"
    prostori = sections[2]["text"]
    assert "Prostor $\\R^n$ je vektorski prostor." in prostori and "komentar" not in prostori
    assert "50\\% cene" in prostori
    assert sections[3]["heading"] == "Vektorski prostori › Baza" and "% to ostane" in sections[3]["text"]


def test_connector_import_allowlist_and_web_extensions_match_the_server(owner_api: Api) -> None:
    from recallspring_api.ingest.storage import ALLOWED_EXTENSIONS

    server = Path(__file__).parents[2] / "mcp" / "src" / "recallspring_mcp" / "server.py"
    source = server.read_text(encoding="utf-8")
    block = source[source.index("CODE_EXTENSIONS = {") : source.index("OLD_OFFICE")]
    assert set(re.findall(r'"(\.[a-z0-9]+)"', block)) == set(ALLOWED_EXTENSIONS)
    groups = owner_api.get("/sources/limits").json()["extensions"]
    assert ".py" in groups["text"] and ".srt" in groups["text"] and ".csv" in groups["text"]
    assert ".odp" in groups["document"] and ".ipynb" in groups["document"] and ".jpg" in groups["image"]
    assert sorted(groups["document"] + groups["text"] + groups["image"]) == sorted(ALLOWED_EXTENSIONS)
