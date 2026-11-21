"""Claude can look at what text can't carry: PDF pages as images and the pictures inside slides and Word files."""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recallspring_api.config import get_settings
from recallspring_api.ingest import visuals
from recallspring_api.ingest.jobs import run_pending
from recallspring_api.main import create_app

from .conftest import Api, ConnectorApi, make_user
from .office import EMF, PNG_1PX, docx, para, picture, pptx, shape, word_picture
from .pdfs import make_pdf


def course(api: Api) -> str:
    return api.post("/courses", {"title": "Digitalna forenzika"}).json()["id"]


def upload(api: Api, filename: str, content: bytes) -> dict[str, Any]:
    created = api.upload(course(api), filename, content)
    assert created.status_code == 201, created.json()
    run_pending()
    return api.get(f"/sources/{created.json()['id']}").json()


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_pdf_pages_render_as_png_sized_for_claude(owner_api: Api, conn: ConnectorApi) -> None:
    source = upload(owner_api, "skeni.pdf", make_pdf(["Hash funkcije: SHA-256 in MD5.", ""]))
    assert source["parse_state"] == "needs_attention"
    assert source["parse_message"].endswith("Your assistant can look at these pages on request.")

    r = conn.get(f"/sources/{source['id']}/visual", page=2)  # the "scanned" page without text
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["count"] == 2 and body["skipped"] == [] and body["kind"] == "pdf"
    [image] = body["images"]
    assert image["label"] == "p. 2" and image["mime"] == "image/png"
    width, height = png_size(base64.b64decode(image["data"]))
    assert height == 1568 and width == 1212  # US Letter, longest side 1568 px

    missing = conn.get(f"/sources/{source['id']}/visual", page=3)
    assert missing.status_code == 422 and missing.json()["code"] == "page_out_of_range"
    assert missing.json()["message"] == "There is no such page or slide. This file has 2."
    assert conn.get(f"/sources/{source['id']}/visual").json()["code"] == "page_required"


def test_pages_that_would_be_too_large_fall_back_to_grayscale_and_smaller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real_png = visuals.png

    def counting_png(width: int, height: int, stride: int, channels: int, buffer: bytes) -> bytes:
        data = real_png(width, height, stride, channels, buffer)
        sizes.append(channels)
        return data

    monkeypatch.setattr(visuals, "png", counting_png)
    monkeypatch.setattr(visuals, "MAX_PAGE_BYTES", 1)  # nothing fits: every fallback is tried, then reported
    path = tmp_path / "page.pdf"
    path.write_bytes(make_pdf(["Diagram"]))
    result = visuals.render(path, "pdf", 1, 0)
    assert sizes == [3, 1, 1, 1]  # colour first, then grayscale at three sizes
    assert result.images == [] and [(s.label, s.reason) for s in result.skipped] == [("p. 1", "too_large")]


def test_slide_pictures_are_marked_in_the_text_and_shown_with_alt_text(owner_api: Api, conn: ConnectorApi) -> None:
    slides = [
        shape(["Mitohondrij"], "title") + picture("rIdA", "Prerez mitohondrija") + picture("rIdB"),
        shape(["Brez slik na tej prosojnici"], "title"),
    ]
    media = {1: {"rIdA": ("image1.png", PNG_1PX), "rIdB": ("image2.emf", EMF)}}
    source = upload(owner_api, "predavanje.pptx", pptx(slides, media=media))
    sections = owner_api.sections(source["id"])
    assert sections[0]["text"].endswith("[picture 1: Prerez mitohondrija]\n[picture 2]")

    body = conn.get(f"/sources/{source['id']}/visual", page=1).json()
    assert [(i["label"], i["mime"], i["alt"]) for i in body["images"]] == [
        ("slide 1, picture 1", "image/png", "Prerez mitohondrija")
    ]
    assert base64.b64decode(body["images"][0]["data"]) == PNG_1PX  # passed on unchanged
    assert [(s["label"], s["reason"]) for s in body["skipped"]] == [("slide 1, picture 2", "vector_drawing")]
    assert "screenshot" in body["skipped"][0]["message"]

    one = conn.get(f"/sources/{source['id']}/visual", page=1, picture=2).json()
    assert one["images"] == [] and one["skipped"][0]["label"] == "slide 1, picture 2"
    none = conn.get(f"/sources/{source['id']}/visual", page=2)
    assert none.status_code == 404 and none.json()["code"] == "no_pictures"
    assert conn.get(f"/sources/{source['id']}/visual", page=1, picture=3).json()["code"] == "picture_out_of_range"


def test_word_pictures_are_numbered_once_and_viewable(owner_api: Api, conn: ConnectorApi) -> None:
    body = (
        para("Zgradba celice")
        + para(extra=word_picture("rIdImg1", "Shema celice"))
        + para("Besedilo med slikama.")
        + para(extra=word_picture("rIdImg2", "image2.png", with_fallback=False))  # a file name is not alt text
    )
    images = {"rIdImg1": ("image1.png", PNG_1PX), "rIdImg2": ("image2.png", PNG_1PX)}
    source = upload(owner_api, "zapiski.docx", docx(body, images=images))
    text = owner_api.sections(source["id"])[0]["text"]
    assert text == "Zgradba celice\n\n[picture 1: Shema celice]\n\nBesedilo med slikama.\n\n[picture 2]"

    shown = conn.get(f"/sources/{source['id']}/visual", picture=2).json()
    assert [(i["label"], i["alt"]) for i in shown["images"]] == [("picture 2", None)] and shown["count"] == 2
    assert conn.get(f"/sources/{source['id']}/visual", picture=3).json()["code"] == "picture_out_of_range"
    assert conn.get(f"/sources/{source['id']}/visual").json()["code"] == "picture_required"
    assert conn.get(f"/sources/{source['id']}/visual", page=1).json()["code"] == "page_needs_renderer"


def test_word_document_of_only_pictures_needs_attention_not_invented_text(owner_api: Api) -> None:
    content = docx(para(extra=word_picture("rIdImg1")), images={"rIdImg1": ("scan.png", PNG_1PX)})
    source = upload(owner_api, "scan.docx", content)
    assert source["parse_state"] == "needs_attention" and "pictures_only" in source["parse_notes"]
    assert source["parse_message"] == "This document has only pictures. Your assistant can look at them on request."
    assert [s["text"] for s in owner_api.sections(source["id"])] == ["[picture 1]"]


def test_visuals_only_for_own_pdf_word_and_powerpoint_sources(owner_api: Api, conn: ConnectorApi) -> None:
    cid = course(owner_api)
    notes = owner_api.paste(cid, "# Zapiski\n\nBesedilo").json()
    refused = conn.get(f"/sources/{notes['id']}/visual", page=1)
    assert refused.status_code == 409 and refused.json()["code"] == "no_visuals"

    broken = owner_api.upload(cid, "pokvarjen.pdf", b"%PDF-1.4 not really a pdf").json()
    r = conn.get(f"/sources/{broken['id']}/visual", page=1)
    assert r.status_code == 422 and r.json()["code"] == "pdf_unreadable"

    make_user("other")
    with TestClient(create_app()) as client:
        other = Api(client)
        assert other.login("other").status_code == 200
        theirs = other.upload(course(other), "tuje.pdf", make_pdf(["Tuje gradivo"])).json()
    assert conn.get(f"/sources/{theirs['id']}/visual", page=1).status_code == 404


def test_rendering_runs_in_the_isolated_process(
    owner_api: Api, conn: ConnectorApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = upload(owner_api, "izolirano.pdf", make_pdf(["Upodobljeno v locenem procesu."]))
    monkeypatch.setattr(get_settings(), "extraction_isolation", "subprocess")
    r = conn.get(f"/sources/{source['id']}/visual", page=1)
    assert r.status_code == 200, r.json()
    assert png_size(base64.b64decode(r.json()["images"][0]["data"]))[1] == 1568
