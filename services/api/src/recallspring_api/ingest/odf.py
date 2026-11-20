"""Text from OpenDocument files (LibreOffice, OpenOffice, Google Docs exports): .odt, .odp and .ods.

They are ZIP packages like Office files, read with the same guards (office.Package: ZIP directory checked first,
size budget, no DTD/entities, expat). The package must declare its type in the ``mimetype`` entry; a package
whose manifest lists encryption data is password-protected and refused. Only content.xml (and styles of
tables, to skip hidden sheets) is read; macros, scripts, embedded objects and links are never opened.
Pictures are numbered ("[picture N]") in reading order so Claude can look at them with view_page.
"""

from __future__ import annotations

import io
import posixpath
import re
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree as ET

from .extract import (
    EXTRACTOR_VERSION,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    MIN_PAGE_CHARS,
    NEEDS_ATTENTION_EMPTY_SHARE,
    Blocks,
    Result,
    Section,
    _split_long,
    _with_offsets,
    normalize,
    sections_from_blocks,
)
from .office import _DTD_MARKERS, Package, PackageError, _alt_text, picture_marker, table_sections

MIMETYPES = {
    "odt": "application/vnd.oasis.opendocument.text",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
}
_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "presentation": "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}
MAX_REPEAT = 100  # repeated rows/columns that carry a value are expanded at most this often


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


TEXT_P, TEXT_H, TEXT_LIST, TEXT_LIST_ITEM, TEXT_LIST_HEADER = (
    _q("text", n) for n in ("p", "h", "list", "list-item", "list-header")
)
TEXT_SPACE, TEXT_TAB, TEXT_BREAK, TEXT_NOTE, TEXT_NOTE_BODY, TEXT_NOTE_CITATION = (
    _q("text", n) for n in ("s", "tab", "line-break", "note", "note-body", "note-citation")
)
TEXT_SECTION, TEXT_TRACKED = _q("text", "section"), _q("text", "tracked-changes")
TABLE_TABLE, TABLE_ROW, TABLE_CELL, TABLE_COVERED = (
    _q("table", n) for n in ("table", "table-row", "table-cell", "covered-table-cell")
)
DRAW_FRAME, DRAW_IMAGE, DRAW_TEXT_BOX, DRAW_PAGE, DRAW_G, DRAW_A = (
    _q("draw", n) for n in ("frame", "image", "text-box", "page", "g", "a")
)
PRES_NOTES = _q("presentation", "notes")
ANNOTATIONS = {_q("office", "annotation"), _q("office", "annotation-end")}
# Containers whose text duplicates or is not part of the document: indexes, tracked deletions, comments, forms.
_SKIP = {
    TEXT_TRACKED,
    _q("text", "table-of-content"),
    _q("text", "alphabetical-index"),
    _q("text", "illustration-index"),
    _q("text", "table-index"),
    _q("text", "object-index"),
    _q("text", "user-index"),
    _q("text", "bibliography"),
    _q("text", "sequence-decls"),
    _q("text", "variable-decls"),
    _q("text", "user-field-decls"),
    _q("office", "forms"),
    TEXT_NOTE_CITATION,
    *ANNOTATIONS,
}
_RASTER = re.compile(r"(?i)\.(png|jpe?g|gif|webp|bmp|tiff?)$")


# ---------------------------------------------------------------- package


def open_package(path: Path, kind: str) -> Package:
    """An unencrypted OpenDocument package of the declared kind. Raises PackageError."""
    package = Package(path)
    try:
        mimetype = (package.read("mimetype") or b"").strip().decode("ascii", "replace")
        if mimetype != MIMETYPES[kind]:
            raise PackageError("content_does_not_match_type")
        manifest = package.xml("META-INF/manifest.xml")
        if manifest is not None and any(el.tag.endswith("}encryption-data") for el in manifest.iter()):
            raise PackageError("office_protected")
        if "content.xml" not in package.entries:
            raise PackageError("office_unreadable")
    except BaseException:
        package.close()
        raise
    return package


def check_package(path: Path, kind: str) -> None:
    open_package(path, kind).close()


# ---------------------------------------------------------------- pictures

# A picture: (its frame, the package parts of its images in order of preference, alt text). The text markers and
# view_page use the same list, so "[picture 3]" always names the same image.
OdfPicture = tuple[ET.Element, list[str], str | None]


def _image_parts(frame: ET.Element) -> list[str]:
    parts: list[str] = []
    for image in frame.findall(DRAW_IMAGE):
        href = (image.get(_q("xlink", "href")) or "").strip()
        if not href or "://" in href or href.startswith("/"):
            continue  # linked from outside the package: never fetched
        part = posixpath.normpath(href[2:] if href.startswith("./") else href)
        if not part.startswith(".."):
            parts.append(part)
    return sorted(parts, key=lambda p: 0 if _RASTER.search(p) else 1)  # LibreOffice adds a PNG next to an SVG


def _frame_alt(frame: ET.Element) -> str | None:
    for name in ("title", "desc"):
        el = frame.find(_q("svg", name))
        if el is not None and (alt := _alt_text("".join(el.itertext()))):
            return alt
    return None


def pictures(root: ET.Element | None) -> list[OdfPicture]:
    found: list[OdfPicture] = []

    def visit(el: ET.Element) -> None:
        for child in el:
            if child.tag in _SKIP:
                continue
            if child.tag == DRAW_FRAME and child.find(DRAW_IMAGE) is not None:
                found.append((child, _image_parts(child), _frame_alt(child)))
            visit(child)

    if root is not None:
        visit(root)
    return found


def _content(package: Package) -> ET.Element:
    root = package.xml("content.xml")
    if root is None:
        raise PackageError("office_unreadable")
    return root


def _body(root: ET.Element, name: str) -> ET.Element | None:
    body = root.find(_q("office", "body"))
    return body.find(_q("office", name)) if body is not None else None


def slides(root: ET.Element) -> list[ET.Element]:
    presentation = _body(root, "presentation")
    return presentation.findall(DRAW_PAGE) if presentation is not None else []


def document_pictures(package: Package) -> list[tuple[list[str], str | None]]:
    root = _content(package)
    return [(parts, alt) for _, parts, alt in pictures(_body(root, "text"))]


def slide_pictures(package: Package) -> list[list[tuple[list[str], str | None]]]:
    return [[(parts, alt) for _, parts, alt in pictures(page)] for page in slides(_content(package))]


# ---------------------------------------------------------------- text


class _Text:
    """Walks text content (documents, text boxes on slides) into lines and heading blocks."""

    def __init__(self, numbered: dict[int, tuple[int, str | None]]) -> None:
        self.numbered = numbered  # id(frame) -> (picture number, alt)
        self.blocks: Blocks = [([], [])]
        self.path: list[str] = []
        self.chars = 0
        self.truncated = False

    def add(self, text: str) -> None:
        if self.chars > MAX_TEXT_CHARS:
            self.truncated = True
            return
        self.chars += len(text)
        self.blocks[-1][1].append(text)

    def inline(self, el: ET.Element, out: list[str], boxes: list[ET.Element]) -> None:
        if el.text:
            out.append(el.text)
        for child in el:
            tag = child.tag
            if tag == TEXT_SPACE:
                count = child.get(_q("text", "c")) or "1"
                out.append(" " * min(int(count) if count.isdigit() else 1, 40))
            elif tag == TEXT_TAB:
                out.append(" ")
            elif tag == TEXT_BREAK:
                out.append("\n")
            elif tag in _SKIP:
                pass
            elif tag == TEXT_NOTE:
                body = child.find(TEXT_NOTE_BODY)
                note = " ".join(self.plain(body).split()) if body is not None else ""
                if note:
                    out.append(f" [note: {note}]")
            elif tag == DRAW_FRAME:
                if id(child) in self.numbered:
                    out.append(" " + picture_marker(*self.numbered[id(child)]) + " ")
                boxes.extend(child.findall(DRAW_TEXT_BOX))
            elif tag == DRAW_A:
                self.inline(child, out, boxes)
            else:
                self.inline(child, out, boxes)
            if child.tail:
                out.append(child.tail)

    def plain(self, el: ET.Element) -> str:
        out: list[str] = []
        for p in el.iter():
            if p.tag in (TEXT_P, TEXT_H):
                parts: list[str] = []
                self.inline(p, parts, [])
                out.append("".join(parts))
        return "\n".join(out)

    def paragraph(self, el: ET.Element, prefix: str = "") -> None:
        parts: list[str] = []
        boxes: list[ET.Element] = []
        self.inline(el, parts, boxes)
        text = "\n".join(" ".join(line.split()) for line in "".join(parts).split("\n")).strip()
        if text:
            self.add(prefix + text)
        for box in boxes:
            self.walk(box)

    def heading(self, el: ET.Element) -> None:
        raw = el.get(_q("text", "outline-level")) or "1"
        level = max(1, min(int(raw) if raw.isdigit() else 1, 9))
        parts: list[str] = []
        self.inline(el, parts, [])
        title = " ".join("".join(parts).split())
        if not title:
            return
        self.path = self.path[: level - 1] + [title[:200]]
        self.blocks.append((list(self.path), []))
        self.add("#" * min(level, 6) + " " + title)

    def list(self, el: ET.Element, depth: int = 0) -> None:
        for item in el:
            if item.tag not in (TEXT_LIST_ITEM, TEXT_LIST_HEADER):
                continue
            for child in item:
                if child.tag in (TEXT_P, TEXT_H):
                    self.paragraph(child, "  " * depth + "- ")
                elif child.tag == TEXT_LIST:
                    self.list(child, depth + 1)

    def table(self, el: ET.Element) -> None:
        rows: list[str] = []
        for row in el.iter(TABLE_ROW):
            cells = []
            for cell in row:
                if cell.tag in (TABLE_CELL, TABLE_COVERED):
                    cells.append(" ".join(self.plain(cell).split()))
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            self.add("\n".join(rows))

    def walk(self, container: Iterable[ET.Element] | None) -> None:
        for el in container if container is not None else []:
            tag = el.tag
            if tag in _SKIP:
                continue
            if tag == TEXT_H:
                self.heading(el)
            elif tag == TEXT_P:
                self.paragraph(el)
            elif tag == TEXT_LIST:
                self.list(el)
            elif tag == TABLE_TABLE:
                self.table(el)
            elif tag == DRAW_FRAME:  # anchored to the page, outside any paragraph
                if id(el) in self.numbered:
                    self.add(picture_marker(*self.numbered[id(el)]))
                self.walk(el)  # text boxes and tables inside the frame
            else:
                self.walk(el)  # sections, groups, custom shapes with text


def _numbered(found: list[OdfPicture]) -> dict[int, tuple[int, str | None]]:
    return {id(frame): (number, alt) for number, (frame, _, alt) in enumerate(found, start=1)}


_MARKER = re.compile(r"\[picture \d+(?::[^\]]*)?\]")


def extract_odt(package: Package, version: str) -> Result:
    root = _content(package)
    text = _body(root, "text")
    found = pictures(text)
    walker = _Text(_numbered(found))
    walker.walk(text)
    sections = sections_from_blocks([(p, [normalize("\n\n".join(lines))]) for p, lines in walker.blocks], "\n")
    notes = [f"pictures_not_extracted:{len(found)}"] if found else []
    notes += ["truncated"] if walker.truncated else []
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", notes=notes)
    if not _MARKER.sub("", "\n".join(s.text for s in sections)).strip():
        return Result("needs_attention", version, sections, notes=[*notes, "pictures_only"])
    return Result("needs_attention" if walker.truncated else "ready", version, sections, notes=notes)


def _is_title(frame: ET.Element) -> bool:
    return frame.get(_q("presentation", "class")) in ("title", "subtitle")


def extract_odp(package: Package, version: str, max_pages: int) -> Result:
    root = _content(package)
    pages = slides(root)
    if len(pages) > max_pages:
        return Result("failed", version, error_code="too_many_pages", page_count=len(pages))
    sections: list[Section] = []
    empty: list[int] = []
    chars = 0
    truncated = False
    total_pictures = 0
    for number, page in enumerate(pages, start=1):
        found = pictures(page)
        total_pictures += len(found)
        title_walker, body_walker = _Text({}), _Text({})
        for frame in page:
            if frame.tag == PRES_NOTES:
                continue
            target = title_walker if frame.tag == DRAW_FRAME and _is_title(frame) else body_walker
            target.walk([frame])
        notes_el = page.find(PRES_NOTES)
        notes_walker = _Text({})
        if notes_el is not None:
            for frame in notes_el.findall(DRAW_FRAME):
                for box in frame.findall(DRAW_TEXT_BOX):
                    notes_walker.walk(box)
        title = " ".join(" ".join(line for _, lines in title_walker.blocks for line in lines).split())[:300]
        title = title.lstrip("# ")
        body = normalize("\n".join(line for _, lines in body_walker.blocks for line in lines))
        if len(title) + len(body) < MIN_PAGE_CHARS:
            empty.append(number)
        parts = [f"# {title}"] if title else []
        parts += [body] if body else []
        if found:
            parts.append("\n".join(picture_marker(i, alt) for i, (_, _, alt) in enumerate(found, start=1)))
        spoken = normalize("\n".join(line for _, lines in notes_walker.blocks for line in lines))
        parts += [f"Speaker notes:\n{spoken}"] if spoken else []
        text = normalize("\n\n".join(parts))
        if not text:
            continue
        if chars > MAX_TEXT_CHARS:
            truncated = True
            break
        chars += len(text)
        name = page.get(_q("draw", "name")) or ""
        heading = title or (name if name and not re.fullmatch(r"(?i)(page|slide)\s*\d+", name) else None)
        chunks = _split_long(text, MAX_SECTION_CHARS)
        for i, chunk in enumerate(chunks):
            label = f"slide {number}" if len(chunks) == 1 else f"slide {number} ({i + 1}/{len(chunks)})"
            sections.append(Section(0, label, chunk, page=number, heading=heading[:300] if heading else None))
    notes = [f"pictures_not_extracted:{total_pictures}"] if total_pictures else []
    if empty:
        notes.append("slides_without_text:" + ",".join(map(str, empty)))
    if truncated:
        notes.append("truncated")
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", notes=notes, page_count=len(pages))
    mostly_pictures = len(empty) / max(1, len(pages)) > NEEDS_ATTENTION_EMPTY_SHARE
    status = "needs_attention" if mostly_pictures or truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes, page_count=len(pages))


# ---------------------------------------------------------------- spreadsheets


def _repeat(el: ET.Element, name: str) -> int:
    raw = el.get(_q("table", name)) or "1"
    return int(raw) if raw.isdigit() and int(raw) > 0 else 1


def _cell_text(cell: ET.Element) -> str:
    """What the cell shows (its paragraphs); the stored value when it shows nothing."""
    shown = "\n".join("".join(p.itertext()) for p in cell.iter(TEXT_P))
    if shown.strip():
        return " ".join(shown.split())
    for attr in ("value", "date-value", "time-value", "boolean-value", "string-value"):
        if value := cell.get(_q("office", attr)):
            return value
    return ""


def extract_ods(package: Package, version: str, max_pages: int) -> Result:
    data = package.read("content.xml") or b""
    if any(marker in data for marker in _DTD_MARKERS):
        raise PackageError("unsafe_document")
    hidden_styles: set[str] = set()
    sheets: list[tuple[str, bool, list[tuple[int, str]]]] = []
    current: list[tuple[int, str]] | None = None
    row_number = 0
    try:
        for event, el in ET.iterparse(io.BytesIO(data), events=("start", "end")):
            tag = el.tag
            if event == "start":
                if tag == TABLE_TABLE and current is None:
                    current, row_number = [], 0
                    name = el.get(_q("table", "name")) or f"Sheet {len(sheets) + 1}"
                    sheets.append((name, el.get(_q("table", "style-name")) in hidden_styles, current))
                continue
            if tag == _q("style", "style"):
                props = el.find(_q("style", "table-properties"))
                if props is not None and props.get(_q("table", "display")) == "false":
                    hidden_styles.add(el.get(_q("style", "name")) or "")
            elif tag == TABLE_ROW and current is not None:
                repeat = _repeat(el, "number-rows-repeated")
                cells: list[str] = []
                for cell in el:
                    if cell.tag not in (TABLE_CELL, TABLE_COVERED):
                        continue
                    value, columns = _cell_text(cell), _repeat(cell, "number-columns-repeated")
                    if value:
                        cells.extend([value] * min(columns, MAX_REPEAT))
                    elif len(cells) < 1000:  # empty cells only keep the columns in place
                        cells.extend([""] * min(columns, 1000))
                while cells and not cells[-1]:
                    cells.pop()
                if cells:
                    for _ in range(min(repeat, MAX_REPEAT)):
                        row_number += 1
                        current.append((row_number, f"Row {row_number}: " + " | ".join(cells[:1000])))
                    row_number += repeat - min(repeat, MAX_REPEAT)
                else:
                    row_number += repeat
                el.clear()
            elif tag == TABLE_TABLE:
                current = None
    except ET.ParseError as exc:
        raise PackageError("office_unreadable") from exc
    if len(sheets) > max_pages:
        return Result("failed", version, error_code="too_many_pages", page_count=len(sheets))
    sections: list[Section] = []
    chars = 0
    truncated = False
    hidden = 0
    for name, is_hidden, lines in sheets:
        if is_hidden:
            hidden += 1
            continue
        if not lines:
            continue
        found, chars, truncated = table_sections(name, lines, chars)
        sections.extend(found)
        if truncated:
            break
    notes = [f"hidden_sheets:{hidden}"] if hidden else []
    notes += ["truncated"] if truncated else []
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", notes=notes, page_count=len(sheets))
    return Result(
        "needs_attention" if truncated else "ready",
        version,
        _with_offsets(sections),
        notes=notes,
        page_count=len(sheets),
    )


# ---------------------------------------------------------------- entry point


def extract(path: Path, kind: str, max_pages: int) -> Result:
    version = f"{EXTRACTOR_VERSION}/{kind}-stdlib-1"
    try:
        package = open_package(path, kind)
    except PackageError as exc:
        return Result("failed", version, error_code=exc.code)
    try:
        if kind == "odt":
            return extract_odt(package, version)
        if kind == "odp":
            return extract_odp(package, version, max_pages)
        return extract_ods(package, version, max_pages)
    except PackageError as exc:
        return Result("failed", version, error_code=exc.code)
    except Exception:  # noqa: BLE001 - any parser failure is reported as unreadable, never raised
        return Result("failed", version, error_code="office_unreadable")
    finally:
        package.close()
