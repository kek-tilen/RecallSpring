"""Pictures Claude can't take as they are are converted; whole slides and pages come from LibreOffice when installed."""

from __future__ import annotations

import base64
import io
import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from recallspring_api.ingest import renderer, visuals
from recallspring_api.ingest.jobs import run_pending

from .conftest import Api, ConnectorApi
from .odf import image_frame, p, package, slide, text_frame
from .office import PNG_1PX, docx, para, pptx, shape, word_picture
from .pdfs import make_pdf

_COURSES = itertools.count(1)


def upload(api: Api, filename: str, content: bytes) -> dict[str, Any]:
    cid = api.post("/courses", {"title": f"Multimedija {next(_COURSES)}"}).json()["id"]
    created = api.upload(cid, filename, content)
    assert created.status_code == 201, created.json()
    run_pending()
    return api.get(f"/sources/{created.json()['id']}").json()


def image_bytes(fmt: str, size: tuple[int, int], mode: str = "RGB", noise: bool = False, **kw: Any) -> bytes:
    img = Image.frombytes(mode, size, os.urandom(size[0] * size[1] * len(mode))) if noise else Image.new(mode, size)
    out = io.BytesIO()
    img.save(out, fmt, **kw)
    return out.getvalue()


def size_of(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_tiff_and_bmp_pictures_become_png_for_claude(owner_api: Api, conn: ConnectorApi) -> None:
    tiff = image_bytes("TIFF", (3000, 2000), "L")
    bmp = image_bytes("BMP", (64, 48))
    body = para(extra=word_picture("rIdImg1")) + para(extra=word_picture("rIdImg2"))
    images = {"rIdImg1": ("image1.tiff", tiff), "rIdImg2": ("image2.bmp", bmp)}
    source = upload(owner_api, "skeni.docx", docx(body, images=images))
    for number, longest in ((1, 1568), (2, 64)):
        body_json = conn.get(f"/sources/{source['id']}/visual", picture=number).json()
        [image] = body_json["images"]
        assert image["mime"] == "image/png" and image["converted"] is True
        assert max(size_of(base64.b64decode(image["data"]))) == longest


def test_huge_pictures_are_refused_before_decoding(tmp_path: Path) -> None:
    bomb = image_bytes("PNG", (9000, 9000), "1")  # 81 megapixels in a few kilobytes
    assert len(bomb) < visuals.MAX_PICTURE_BYTES
    assert visuals.fit_picture(bomb) == "too_large"
    wide = image_bytes("PNG", (9000, 10), "L")  # small but wider than Claude accepts: made smaller
    fitted = visuals.fit_picture(wide)
    assert not isinstance(fitted, str) and size_of(fitted[1])[0] == 1568


def test_large_photos_are_shrunk_when_claude_looks_at_them(owner_api: Api, conn: ConnectorApi) -> None:
    big = image_bytes("JPEG", (2000, 1600), noise=True, quality=98)
    assert len(big) > visuals.MAX_PICTURE_BYTES
    source = upload(owner_api, "tabla.jpg", big)
    r = conn.get(f"/sources/{source['id']}/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-rs-converted"] == "true" and len(r.content) <= visuals.MAX_PICTURE_BYTES
    assert max(size_of(r.content)) == 1568


def test_opendocument_pictures_are_viewable_with_their_numbers(owner_api: Api, conn: ConnectorApi) -> None:
    text = p("Prva", image_frame("Pictures/a.png", "Shema omrežja")) + p("Druga", image_frame("Pictures/b.svg"))
    odt = package("odt", text, files={"Pictures/a.png": PNG_1PX, "Pictures/b.svg": b"<svg xmlns='x'/>"})
    source = upload(owner_api, "omrezja.odt", odt)
    first = conn.get(f"/sources/{source['id']}/visual", picture=1).json()
    assert [(i["label"], i["alt"]) for i in first["images"]] == [("picture 1", "Shema omrežja")]
    second = conn.get(f"/sources/{source['id']}/visual", picture=2).json()
    assert second["images"] == [] and second["skipped"][0]["reason"] == "vector_drawing"
    assert conn.get(f"/sources/{source['id']}/visual", page=1).json()["code"] == "page_needs_renderer"

    slides = slide(text_frame(p("Usmerjanje"), "title") + image_frame("Pictures/r.png", "Tabela usmerjanja"))
    odp = package("odp", slides, files={"Pictures/r.png": PNG_1PX})
    deck = upload(owner_api, "usmerjanje.odp", odp)
    shown = conn.get(f"/sources/{deck['id']}/visual", page=1).json()
    assert [(i["label"], i["alt"]) for i in shown["images"]] == [("slide 1, picture 1", "Tabela usmerjanja")]
    assert shown["whole_page"] is False


def test_notebook_output_pictures_are_viewable(owner_api: Api, conn: ConnectorApi) -> None:
    png = base64.b64encode(PNG_1PX).decode()
    cells = [
        {
            "cell_type": "code",
            "source": "plot(a)",
            "outputs": [{"output_type": "display_data", "data": {"image/png": png}}],
        },
        {
            "cell_type": "code",
            "source": "plot(b)",
            "outputs": [{"output_type": "display_data", "data": {"image/png": png}}],
        },
    ]
    source = upload(owner_api, "grafi.ipynb", json.dumps({"nbformat": 4, "cells": cells}).encode())
    body = conn.get(f"/sources/{source['id']}/visual", picture=2).json()
    assert body["count"] == 2 and [i["label"] for i in body["images"]] == ["picture 2"]
    assert base64.b64decode(body["images"][0]["data"]) == PNG_1PX
    assert conn.get(f"/sources/{source['id']}/visual", picture=3).json()["code"] == "picture_out_of_range"


def test_whole_slides_and_pages_come_from_libreoffice_when_it_is_installed(
    owner_api: Api, conn: ConnectorApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_convert(soffice: str, source: Path, kind: str, workdir: Path, timeout: int) -> Path:
        calls.append(kind)
        out = workdir / "out"
        out.mkdir()
        (out / "document.pdf").write_bytes(make_pdf(["Diagram s puscicami", "Graf"]))
        return out / "document.pdf"

    monkeypatch.setattr(renderer, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(renderer, "convert", fake_convert)
    deck = upload(owner_api, "predavanje.pptx", pptx([shape(["Arhitektura"], "title"), shape(["Graf"], "title")]))
    first = conn.get(f"/sources/{deck['id']}/visual", page=2).json()
    assert first["whole_page"] is True and [i["label"] for i in first["images"]] == ["slide 2"]
    again = conn.get(f"/sources/{deck['id']}/visual", page=1).json()
    assert again["images"][0]["label"] == "slide 1" and calls == ["pptx"]  # converted once, then cached
    pictures = conn.get(f"/sources/{deck['id']}/visual", page=1, picture=1)
    assert pictures.json()["code"] == "picture_out_of_range"  # pictures stay available by number

    doc = upload(owner_api, "porocilo.docx", docx(para("Poročilo")))
    page = conn.get(f"/sources/{doc['id']}/visual", page=1).json()
    assert page["whole_page"] is True and page["images"][0]["label"] == "page 1" and calls == ["pptx", "docx"]
    assert owner_api.get("/sources/limits").json()["page_renderer_available"] is True


def test_without_libreoffice_slides_show_their_pictures_and_documents_explain(
    owner_api: Api, conn: ConnectorApi
) -> None:
    assert renderer.available() is False  # RS_OFFICE_RENDERER=off in tests
    deck = upload(owner_api, "brez.pptx", pptx([shape(["Samo besedilo"], "title")]))
    r = conn.get(f"/sources/{deck['id']}/visual", page=1)
    assert r.status_code == 404 and r.json()["code"] == "no_pictures" and "LibreOffice" in r.json()["message"]
    doc = upload(owner_api, "brez.docx", docx(para("Besedilo")))
    r = conn.get(f"/sources/{doc['id']}/visual", page=1)
    assert r.status_code == 422 and r.json()["code"] == "page_needs_renderer"
    assert owner_api.get("/sources/limits").json()["page_renderer_available"] is False
