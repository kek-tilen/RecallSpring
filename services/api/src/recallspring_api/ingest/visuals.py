"""Pages and pictures as images Claude can look at, made in a separate, time-limited process.

- PDF pages are rendered with PDFium (pypdfium2) to PNG sized for Claude: longest side LONG_EDGE pixels and at
  most MAX_PAGE_BYTES; grayscale and smaller sizes are tried before giving up. Office and OpenDocument pages
  arrive here as a PDF that LibreOffice made (renderer.py), when it is installed.
- Pictures inside Word, PowerPoint, OpenDocument files and notebook outputs, and photos the learner uploaded, are
  passed on unchanged when they are PNG, JPEG, GIF or WebP within MAX_PICTURE_BYTES. Others (TIFF, BMP, or too
  large) are converted by Pillow to a PNG or JPEG of at most LONG_EDGE pixels, with a pixel limit against
  decompression bombs. Vector drawings (EMF/WMF/SVG) are never decoded here: the whole page or slide shows them.

Run directly:  python -I -m recallspring_api.ingest.visuals <kind> <path> <page|0> <picture|0>
Prints one JSON object: {"images": [{label, mime, alt, data (base64)}], "skipped": [...], "count": n, "error": code}
"""

from __future__ import annotations

import base64
import io
import json
import struct
import subprocess
import sys
import warnings
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LONG_EDGE = 1568  # Claude's recommended longest side: larger images are scaled down on its side anyway
MAX_PAGE_BYTES = 3_500_000
MAX_PICTURE_BYTES = 4_500_000  # same limit as photos the learner uploads (view_image)
MAX_IMAGES = 4
MAX_TOTAL_BYTES = 9_000_000
MAX_PIXELS = 60_000_000  # a larger picture is refused before it is decoded (decompression bombs)
MAX_EDGE_UNCHANGED = 8000  # Claude refuses images wider or taller than this, however small the file
PILLOW_FORMATS = ["PNG", "JPEG", "GIF", "WEBP", "TIFF", "BMP"]


@dataclass
class Visual:
    label: str
    mime: str
    data: bytes
    alt: str | None = None
    converted: bool = False  # made smaller or turned into PNG/JPEG for Claude


@dataclass
class Skipped:
    label: str
    reason: str  # vector_drawing | unsupported_format | too_large | limit | missing


@dataclass
class VisualResult:
    images: list[Visual] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    count: int = 0  # pages (PDF), slides, or pictures (documents, notebooks) in the file
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "images": [
                {
                    "label": v.label,
                    "mime": v.mime,
                    "alt": v.alt,
                    "converted": v.converted,
                    "data": base64.b64encode(v.data).decode(),
                }
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
                Visual(
                    i["label"],
                    i["mime"],
                    base64.b64decode(i["data"], validate=True),
                    i.get("alt"),
                    bool(i.get("converted")),
                )
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


def _is_vector(data: bytes) -> bool:
    head = data[:64].lstrip()
    is_emf = data[:4] == b"\x01\x00\x00\x00" and data[40:44] == b" EMF"
    is_wmf = data[:4] == b"\xd7\xcd\xc6\x9a" or data[:4] in (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00")
    return is_emf or is_wmf or head.startswith((b"<svg", b"<?xml"))


def _convert(data: bytes, mime: str | None) -> tuple[str, bytes] | None:
    """A PNG or JPEG of at most LONG_EDGE pixels and MAX_PICTURE_BYTES, or None when Pillow can't (or won't)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=PILLOW_FORMATS) as img:
                if img.format == "JPEG":
                    img.draft("RGB", (LONG_EDGE * 2, LONG_EDGE * 2))  # decode at a reduced size
                photo = img.format == "JPEG" or mime == "image/jpeg"
                if "A" in img.getbands() or "transparency" in img.info:
                    frame = img.convert("RGBA")
                    base = Image.new("RGB", frame.size, "white")
                    base.paste(frame, mask=frame.getchannel("A"))
                else:
                    base = img.convert("L" if img.mode in ("1", "L", "I", "I;16", "F") else "RGB")
                base.thumbnail((LONG_EDGE, LONG_EDGE))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError, SyntaxError):
        return None
    attempts = [("JPEG", 85), ("JPEG", 70)] if photo else [("PNG", 0), ("JPEG", 85), ("JPEG", 70)]
    for fmt, quality in attempts:
        out = io.BytesIO()
        base.save(out, fmt, **({"quality": quality} if fmt == "JPEG" else {"optimize": True}))
        if out.tell() <= MAX_PICTURE_BYTES:
            return ("image/jpeg" if fmt == "JPEG" else "image/png"), out.getvalue()
    return None


def _dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height from the header only (nothing is decoded)."""
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(data), formats=PILLOW_FORMATS) as img:
                return img.size
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def fit_picture(data: bytes) -> tuple[str, bytes, bool] | str:
    """(mime, data, converted) Claude can look at, or the reason it can't be shown."""
    mime = image_mime(data)
    if mime and len(data) <= MAX_PICTURE_BYTES:
        size = _dimensions(data)
        if size is not None and max(size) <= MAX_EDGE_UNCHANGED:
            return mime, data, False
    if _is_vector(data):
        return "vector_drawing"
    converted = _convert(data, mime)
    if converted:
        return converted[0], converted[1], True
    return "too_large" if mime else "unsupported_format"


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


def pdf_page(path: Path, page: int, label: str = "p.") -> VisualResult:
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
                    return VisualResult([Visual(f"{label} {page}", "image/png", data)], count=count)
            return VisualResult(skipped=[Skipped(f"{label} {page}", "too_large")], count=count)
        finally:
            canvas.close()
    except pdfium.PdfiumError:
        return VisualResult(error="render_failed")
    finally:
        document.close()


# ---------------------------------------------------------------- pictures

Parts = list[str] | str | None  # a picture may have several parts (LibreOffice keeps a PNG copy next to an SVG)


def _pictures(read: Any, chosen: list[tuple[int, Parts, str | None]], label: str, count: int) -> VisualResult:
    """``read(part)`` gives a picture's bytes, or None."""
    result = VisualResult(count=count)
    total = 0
    for number, parts, alt in chosen:
        name = f"{label}picture {number}"
        candidates = parts if isinstance(parts, list) else [parts] if parts else []
        fitted: tuple[str, bytes, bool] | str = "missing"
        for part in candidates:
            data = read(part)
            if data is None:
                continue
            fitted = fit_picture(data)
            if not isinstance(fitted, str):
                break
        if isinstance(fitted, str):
            result.skipped.append(Skipped(name, fitted))
        elif len(result.images) >= MAX_IMAGES or total + len(fitted[1]) > MAX_TOTAL_BYTES:
            result.skipped.append(Skipped(name, "limit"))
        else:
            total += len(fitted[1])
            result.images.append(Visual(name, fitted[0], fitted[1], alt, fitted[2]))
    return result


def _numbered(pictures: list[tuple[Parts, str | None]], picture: int) -> list[tuple[int, Parts, str | None]]:
    numbered = [(i, parts, alt) for i, (parts, alt) in enumerate(pictures, start=1)]
    return [numbered[picture - 1]] if picture else numbered


def _document_pictures(read: Any, pictures: list[tuple[Parts, str | None]], picture: int) -> VisualResult:
    if not picture:
        return VisualResult(count=len(pictures), error="picture_required")
    if not 1 <= picture <= len(pictures):
        return VisualResult(count=len(pictures), error="picture_out_of_range")
    return _pictures(read, _numbered(pictures, picture), "", len(pictures))


def _slide_pictures(
    read: Any, pictures: list[tuple[Parts, str | None]], page: int, picture: int, slides: int
) -> VisualResult:
    if picture and not 1 <= picture <= len(pictures):
        return VisualResult(count=slides, error="picture_out_of_range")
    result = _pictures(read, _numbered(pictures, picture), f"slide {page}, ", slides)
    if not pictures:
        result.error = "no_pictures"
    return result


def office_pictures(path: Path, kind: str, page: int, picture: int) -> VisualResult:
    from . import office

    try:
        package = office.Package(path)
    except office.PackageError as exc:
        return VisualResult(error=exc.code)
    try:
        if kind == "docx":
            return _document_pictures(package.read, office.docx_pictures(package), picture)
        slides = office.presentation_slides(package)
        if not 1 <= page <= len(slides):
            return VisualResult(count=len(slides), error="page_out_of_range" if page else "page_required")
        pictures = office.slide_pictures(package, slides[page - 1])
        return _slide_pictures(package.read, pictures, page, picture, len(slides))
    except office.PackageError as exc:
        return VisualResult(error=exc.code)
    finally:
        package.close()


def odf_pictures(path: Path, kind: str, page: int, picture: int) -> VisualResult:
    from . import odf
    from .office import PackageError

    try:
        package = odf.open_package(path, kind)
    except PackageError as exc:
        return VisualResult(error=exc.code)
    try:
        if kind == "odt":
            return _document_pictures(package.read, odf.document_pictures(package), picture)
        slides = odf.slide_pictures(package)
        if not 1 <= page <= len(slides):
            return VisualResult(count=len(slides), error="page_out_of_range" if page else "page_required")
        return _slide_pictures(package.read, slides[page - 1], page, picture, len(slides))
    except PackageError as exc:
        return VisualResult(error=exc.code)
    finally:
        package.close()


def notebook_pictures(path: Path, picture: int) -> VisualResult:
    from .formats import notebook_cells, notebook_images

    try:
        _, cells = notebook_cells(path.read_bytes())
    except (ValueError, UnicodeDecodeError, RecursionError):
        return VisualResult(error="notebook_unreadable")
    images = notebook_images(cells)

    def read(number: str) -> bytes | None:
        try:
            return base64.b64decode("".join(images[int(number) - 1][1].split()), validate=True)
        except (IndexError, ValueError):
            return None

    return _document_pictures(read, [(str(i), None) for i in range(1, len(images) + 1)], picture)


def photo(path: Path) -> VisualResult:
    """An uploaded photo, made small enough for Claude when it is too large to send as it is."""
    fitted = fit_picture(path.read_bytes())
    if isinstance(fitted, str):
        return VisualResult(skipped=[Skipped("photo", fitted)], count=1)
    return VisualResult([Visual("photo", fitted[0], fitted[1], None, fitted[2])], count=1)


# ---------------------------------------------------------------- entry points


def render(path: Path, kind: str, page: int, picture: int) -> VisualResult:
    if kind == "pdf":
        return pdf_page(path, page) if page else VisualResult(error="page_required")
    if kind in ("rendered-slides", "rendered-pages"):  # a PDF that LibreOffice made from an Office file
        label = "slide" if kind == "rendered-slides" else "page"
        return pdf_page(path, page, label) if page else VisualResult(error="page_required")
    if kind in ("pptx", "docx"):
        return office_pictures(path, kind, page, picture)
    if kind in ("odp", "odt"):
        return odf_pictures(path, kind, page, picture)
    if kind == "notebook":
        return notebook_pictures(path, picture)
    if kind == "image":
        return photo(path)
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
