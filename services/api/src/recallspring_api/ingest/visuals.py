"""Pages and pictures as images Claude can look at, made in a separate, time-limited process.

- PDF pages are rendered with PDFium (pypdfium2) to PNG sized for Claude: longest side LONG_EDGE pixels and at
  most MAX_PAGE_BYTES; grayscale and smaller sizes are tried before giving up.
- Pictures inside Word and PowerPoint files are passed on unchanged when their bytes are PNG, JPEG, GIF or WebP.
  Vector drawings (EMF/WMF/SVG), TIFF and BMP are reported, never converted. Only PDFium decodes anything.

Run directly:  python -I -m recallspring_api.ingest.visuals <pdf|pptx|docx> <path> <page|0> <picture|0>
Prints one JSON object: {"images": [{label, mime, alt, data (base64)}], "skipped": [...], "count": n, "error": code}
"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LONG_EDGE = 1568  # Claude's recommended longest side: larger images are scaled down on its side anyway
MAX_PAGE_BYTES = 3_500_000
MAX_PICTURE_BYTES = 4_500_000  # same limit as photos the learner uploads (view_image)
MAX_IMAGES = 4
MAX_TOTAL_BYTES = 9_000_000


@dataclass
class Visual:
    label: str
    mime: str
    data: bytes
    alt: str | None = None


@dataclass
class Skipped:
    label: str
    reason: str  # vector_drawing | unsupported_format | too_large | limit | missing


@dataclass
class VisualResult:
    images: list[Visual] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    count: int = 0  # pages (PDF), slides (PowerPoint) or pictures (Word) in the file
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "images": [
                {"label": v.label, "mime": v.mime, "alt": v.alt, "data": base64.b64encode(v.data).decode()}
                for v in self.images
            ],
            "skipped": [asdict(s) for s in self.skipped],
            "count": self.count,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualResult:
        return cls(
            images=[
                Visual(i["label"], i["mime"], base64.b64decode(i["data"], validate=True), i.get("alt"))
                for i in data["images"]
            ],
            skipped=[Skipped(**s) for s in data["skipped"]],
            count=int(data["count"]),
            error=data["error"],
        )


# ---------------------------------------------------------------- formats


def image_mime(data: bytes) -> str | None:
    """Formats Claude can look at, recognised by their bytes (never by name)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _unsupported_reason(data: bytes) -> str:
    head = data[:64].lstrip()
    is_emf = data[:4] == b"\x01\x00\x00\x00" and data[40:44] == b" EMF"
    is_wmf = data[:4] == b"\xd7\xcd\xc6\x9a" or data[:4] in (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00")
    if is_emf or is_wmf or head.startswith((b"<svg", b"<?xml")):
        return "vector_drawing"
    return "unsupported_format"


def png(width: int, height: int, stride: int, channels: int, buffer: bytes) -> bytes:
    """Encode an 8-bit grayscale or RGB bitmap as PNG (no filtering), with the standard library only."""
    color_type = {1: 0, 3: 2}[channels]
    row = width * channels
    raw = b"".join(b"\x00" + buffer[y * stride : y * stride + row] for y in range(height))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


# ---------------------------------------------------------------- PDF pages


def pdf_page(path: Path, page: int) -> VisualResult:
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        return VisualResult(error="pdf_encrypted" if "password" in str(exc).lower() else "pdf_unreadable")
    try:
        count = len(document)
        if not 1 <= page <= count:
            return VisualResult(count=count, error="page_out_of_range")
        canvas = document[page - 1]
        try:
            width, height = canvas.get_size()
            base = min(4.0, (LONG_EDGE - 0.5) / max(width, height, 1.0))  # pdfium rounds the size up
            for scale, gray in ((base, False), (base, True), (base * 0.75, True), (base * 0.55, True)):
                bitmap = canvas.render(scale=scale, grayscale=gray, rev_byteorder=True)
                try:
                    if bitmap.n_channels not in (1, 3):
                        return VisualResult(count=count, error="render_failed")
                    data = png(bitmap.width, bitmap.height, bitmap.stride, bitmap.n_channels, bytes(bitmap.buffer))
                finally:
                    bitmap.close()
                if len(data) <= MAX_PAGE_BYTES:
                    return VisualResult([Visual(f"p. {page}", "image/png", data)], count=count)
            return VisualResult(skipped=[Skipped(f"p. {page}", "too_large")], count=count)
        finally:
            canvas.close()
    except pdfium.PdfiumError:
        return VisualResult(error="render_failed")
    finally:
        document.close()


# ---------------------------------------------------------------- pictures in Word and PowerPoint


def _pictures(package: Any, chosen: list[tuple[int, str | None, str | None]], label: str, count: int) -> VisualResult:
    result = VisualResult(count=count)
    total = 0
    for number, part, alt in chosen:
        name = f"{label}picture {number}"
        data = package.read(part) if part else None
        if data is None:
            result.skipped.append(Skipped(name, "missing"))
            continue
        mime = image_mime(data)
        if mime is None:
            result.skipped.append(Skipped(name, _unsupported_reason(data)))
        elif len(data) > MAX_PICTURE_BYTES:
            result.skipped.append(Skipped(name, "too_large"))
        elif len(result.images) >= MAX_IMAGES or total + len(data) > MAX_TOTAL_BYTES:
            result.skipped.append(Skipped(name, "limit"))
        else:
            total += len(data)
            result.images.append(Visual(name, mime, data, alt))
    return result


def office_pictures(path: Path, kind: str, page: int, picture: int) -> VisualResult:
    from . import office

    try:
        package = office.Package(path)
    except office.PackageError as exc:
        return VisualResult(error=exc.code)
    try:
        if kind == "docx":
            pictures = office.docx_pictures(package)
            if not picture:
                return VisualResult(count=len(pictures), error="picture_required")
            if not 1 <= picture <= len(pictures):
                return VisualResult(count=len(pictures), error="picture_out_of_range")
            part, alt = pictures[picture - 1]
            return _pictures(package, [(picture, part, alt)], "", len(pictures))
        slides = office.presentation_slides(package)
        if not 1 <= page <= len(slides):
            return VisualResult(count=len(slides), error="page_out_of_range" if page else "page_required")
        pictures = office.slide_pictures(package, slides[page - 1])
        if picture and not 1 <= picture <= len(pictures):
            return VisualResult(count=len(slides), error="picture_out_of_range")
        numbered = [(i, part, alt) for i, (part, alt) in enumerate(pictures, start=1)]
        chosen = [numbered[picture - 1]] if picture else numbered
        result = _pictures(package, chosen, f"slide {page}, ", len(slides))
        if not pictures:
            result.error = "no_pictures"
        return result
    except office.PackageError as exc:
        return VisualResult(error=exc.code)
    finally:
        package.close()


# ---------------------------------------------------------------- entry points


def render(path: Path, kind: str, page: int, picture: int) -> VisualResult:
    if kind == "pdf":
        return pdf_page(path, page) if page else VisualResult(error="page_required")
    if kind in ("pptx", "docx"):
        return office_pictures(path, kind, page, picture)
    return VisualResult(error="no_visuals")


class VisualFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def run(kind: str, path: Path, page: int, picture: int, *, isolation: str, timeout: int) -> VisualResult:
    """Called by the API: render in a separate ``python -I`` process with a timeout (like text extraction)."""
    if isolation == "inprocess":
        return render(path, kind, page, picture)
    cmd = [sys.executable, "-I", "-m", "recallspring_api.ingest.visuals", kind, str(path), str(page), str(picture)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)  # noqa: S603 - fixed argv
    except subprocess.TimeoutExpired as exc:
        raise VisualFailure("render_timeout") from exc
    if proc.returncode != 0:
        raise VisualFailure("render_crashed")
    try:
        return VisualResult.from_dict(json.loads(proc.stdout.decode("utf-8")))
    except (ValueError, TypeError, KeyError) as exc:
        raise VisualFailure("render_crashed") from exc


def main(argv: list[str]) -> int:
    from .extract import _limit_memory

    _limit_memory()
    kind, path, page, picture = argv[1], Path(argv[2]), int(argv[3]), int(argv[4])
    sys.stdout.write(json.dumps(render(path, kind, page, picture).as_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
