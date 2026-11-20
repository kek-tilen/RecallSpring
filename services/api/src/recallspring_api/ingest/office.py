"""Text from Word (.docx), PowerPoint (.pptx/.ppsx) and Excel (.xlsx) files, with the standard library only.

These files are ZIP packages of XML parts. Only the parts that hold text are read, behind these guards:
- the ZIP directory is checked before it is opened: at most MAX_ENTRIES entries and no ZIP64 (Office never needs
  it); every part's size is checked before it is read and the total read is capped, so a "zip bomb" fails;
- XML with a DOCTYPE or entity declaration is refused (Office never writes one); parsing uses the standard
  library's expat (>= 2.4 protects against entity expansion; external entities are never fetched);
- relationship targets resolve inside the package only; external links are ignored;
- macros, embedded objects, pictures, charts and links are never opened, rendered or executed.
Runs inside the isolated, time-limited extraction process (extract.py).
"""

from __future__ import annotations

import io
import posixpath
import re
import struct
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
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

MAX_ENTRIES = 10_000
MAX_PART_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024

MAIN_CONTENT_TYPES = {
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"},
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    },
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"},
}
MEDIA_FOLDER = {"docx": "word/media/", "pptx": "ppt/media/", "xlsx": "xl/media/"}
_DTD_MARKERS = tuple(
    marker.encode(encoding) for marker in ("<!DOCTYPE", "<!ENTITY") for encoding in ("ascii", "utf-16-le", "utf-16-be")
)
_EOCD = b"PK\x05\x06"
_ZIP64_LOCATOR = b"PK\x06\x07"


class PackageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- package access


def _check_zip_directory(path: Path) -> None:
    """Read the end-of-central-directory record ourselves, before zipfile builds its in-memory index."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - 65_557))
        tail = fh.read()
    at = tail.rfind(_EOCD)
    if at < 0 or len(tail) - at < 22:
        raise PackageError("office_unreadable")
    _, _, _, _, entries, _, offset, _ = struct.unpack("<4s4H2LH", tail[at : at + 22])
    if entries == 0xFFFF or offset == 0xFFFFFFFF or (at >= 20 and tail[at - 20 : at - 16] == _ZIP64_LOCATOR):
        raise PackageError("document_too_large")  # ZIP64: never needed by an Office file of an allowed size
    if entries > MAX_ENTRIES:
        raise PackageError("document_too_large")


def parse_xml(data: bytes) -> ET.Element:
    if any(marker in data for marker in _DTD_MARKERS):
        raise PackageError("unsafe_document")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise PackageError("office_unreadable") from exc


def _local(tag: object) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


def _attr(el: ET.Element | None, name: str) -> str | None:
    """Attribute by local name (w:val, val, ...), so transitional and strict namespaces both work."""
    if el is None:
        return None
    for key, value in el.attrib.items():
        if key == name or key.endswith("}" + name):
            return value
    return None


def _rel_id(el: ET.Element, name: str = "id") -> str | None:
    """An r:id / r:embed attribute (relationships namespace), distinct from a plain numeric ``id``."""
    for key, value in el.attrib.items():
        if key.endswith("}" + name) and "relationships" in key:
            return value
    return None


def _child(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    return next((c for c in el if _local(c.tag) == name), None)


def _children(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if el is None else [c for c in el if _local(c.tag) == name]


def _resolve(base_dir: str, target: str) -> str | None:
    target = unquote(target.replace("\\", "/").split("#", 1)[0])
    if not target:
        return None
    path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(base_dir, target))
    if path.startswith("..") or path.startswith("/"):
        return None  # outside the package
    return path


class Package:
    def __init__(self, path: Path) -> None:
        _check_zip_directory(path)
        try:
            self.zip = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise PackageError("office_unreadable") from exc
        self.entries = {info.filename.lower(): info for info in self.zip.infolist()}
        self.budget = MAX_TOTAL_BYTES

    def close(self) -> None:
        self.zip.close()

    def read(self, name: str | None) -> bytes | None:
        info = self.entries.get((name or "").lower())
        if info is None:
            return None
        if info.flag_bits & 0x1:
            raise PackageError("office_unreadable")  # encrypted entry
        if info.file_size > MAX_PART_BYTES or info.file_size > self.budget:
            raise PackageError("document_too_large")
        try:
            with self.zip.open(info) as fh:
                data = fh.read(info.file_size + 1)
        except (zipfile.BadZipFile, OSError, EOFError, NotImplementedError) as exc:
            raise PackageError("office_unreadable") from exc
        if len(data) > info.file_size:
            raise PackageError("document_too_large")
        self.budget -= len(data)
        return data

    def xml(self, name: str | None) -> ET.Element | None:
        data = self.read(name)
        return None if data is None else parse_xml(data)

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """Relationship id -> (type, package path) for a part ("" for the package itself)."""
        base_dir, base_name = posixpath.split(part)
        root = self.xml(posixpath.join(base_dir, "_rels", base_name + ".rels"))
        out: dict[str, tuple[str, str]] = {}
        for rel in root if root is not None else []:
            if _local(rel.tag) != "Relationship" or rel.get("TargetMode") == "External":
                continue
            target = _resolve(base_dir, rel.get("Target", ""))
            if target and rel.get("Id"):
                out[rel.get("Id", "")] = (rel.get("Type", ""), target)
        return out

    def content_type(self, part: str) -> str | None:
        root = self.xml("[Content_Types].xml")
        if root is None:
            return None
        wanted = "/" + part.lower()
        for el in root:
            if _local(el.tag) == "Override" and (el.get("PartName") or "").lower() == wanted:
                return el.get("ContentType")
        ext = posixpath.splitext(part)[1].lstrip(".").lower()
        for el in root:
            if _local(el.tag) == "Default" and (el.get("Extension") or "").lower() == ext:
                return el.get("ContentType")
        return None

    def main_part(self, kind: str) -> str:
        main = next((t for typ, t in self.rels("").values() if typ.endswith("/officeDocument")), None)
        if main is None or self.content_type(main) not in MAIN_CONTENT_TYPES[kind]:
            raise PackageError("content_does_not_match_type")
        return main

    def media_count(self, kind: str) -> int:
        return sum(1 for name in self.entries if name.startswith(MEDIA_FOLDER[kind]))


def _target(rels: dict[str, tuple[str, str]], type_suffix: str) -> str | None:
    return next((t for typ, t in rels.values() if typ.endswith(type_suffix)), None)


def check_package(path: Path, kind: str) -> None:
    """Upload-time check: a real, unencrypted package of the declared kind. Raises PackageError."""
    package = Package(path)
    try:
        package.main_part(kind)
    finally:
        package.close()


# ---------------------------------------------------------------- pictures

# A picture: (its element, relationship id, alt text). Text markers ("[picture 3]") and view_page number pictures
# with the same list, so a marker always names the same image.
PictureRef = tuple[ET.Element, str, str | None]
_WORD_SHAPES = frozenset({"drawing", "pict"})
_SLIDE_SHAPES = frozenset({"sp", "pic", "graphicFrame", "grpSp", "cxnSp"})


_FILE_NAME = re.compile(r"(?i).+\.(png|jpe?g|gif|bmp|emf|wmf|tiff?|svg|webp)")


def _alt_text(text: str | None) -> str | None:
    """Alt text the author wrote; a bare file name ("image1.png") says nothing and is dropped."""
    text = " ".join((text or "").split())[:150]
    return None if not text or _FILE_NAME.fullmatch(text) else text


def _picture_refs(root: ET.Element | None, shapes: frozenset[str]) -> list[PictureRef]:
    """Embedded pictures in document order, skipping fallback copies and deleted content."""
    out: list[PictureRef] = []
    alt: list[str | None] = [None]

    def visit(el: ET.Element) -> None:
        for child in el:
            name = _local(child.tag)
            if name in ("Fallback", "del", "moveFrom"):
                continue
            if name in shapes:
                alt[0] = None
            if name in ("docPr", "cNvPr"):
                alt[0] = _alt_text(child.get("descr") or child.get("title")) or alt[0]
            elif name in ("blip", "imagedata"):
                rid = _rel_id(child, "embed") if name == "blip" else _rel_id(child)
                if rid:
                    out.append((child, rid, alt[0]))
            visit(child)

    if root is not None:
        visit(root)
    return out


def _image_part(rels: dict[str, tuple[str, str]], rid: str) -> str | None:
    typ, target = rels.get(rid, ("", ""))
    return target if typ.endswith("/image") else None


def picture_marker(number: int, alt: str | None) -> str:
    return f"[picture {number}: {alt}]" if alt else f"[picture {number}]"


def docx_pictures(package: Package) -> list[tuple[str | None, str | None]]:
    """(package path, alt text) of each picture in a Word document, numbered from 1 in this order."""
    main = package.main_part("docx")
    rels = package.rels(main)
    return [(_image_part(rels, rid), alt) for _, rid, alt in _picture_refs(package.xml(main), _WORD_SHAPES)]


def presentation_slides(package: Package) -> list[str]:
    """Slide parts in presentation order (not file order)."""
    main = package.main_part("pptx")
    rels = package.rels(main)
    slide_list = _child(package.xml(main), "sldIdLst")
    return [rels[rid][1] for el in _children(slide_list, "sldId") if (rid := _rel_id(el)) in rels]


def slide_pictures(
    package: Package, part: str, slide: ET.Element | None = None, rels: dict[str, tuple[str, str]] | None = None
) -> list[tuple[str | None, str | None]]:
    """(package path, alt text) of the pictures on one slide (backgrounds excluded), numbered from 1."""
    slide = package.xml(part) if slide is None else slide
    rels = package.rels(part) if rels is None else rels
    tree = _child(_child(slide, "cSld"), "spTree")
    return [(_image_part(rels, rid), alt) for _, rid, alt in _picture_refs(tree, _SLIDE_SHAPES)]


# ---------------------------------------------------------------- Word


@dataclass(frozen=True)
class _Style:
    level: int | None  # heading level 1-9, or None for body text
    toc: bool = False  # table-of-contents entry (duplicates the headings)
    list_item: bool = False


_HEADING_NAME = re.compile(r"heading ([1-9])")
_HEADING_ID = re.compile(r"(?i)heading\s?([1-9])")
_DOCX_SKIP = {"pPr", "rPr", "instrText", "delText", "del", "moveFrom", "Fallback", "commentReference", "sectPr"}


def _docx_styles(root: ET.Element | None) -> dict[str, _Style]:
    raw: dict[str, tuple[str, int | None, str | None, bool]] = {}
    for st in root if root is not None else []:
        if _local(st.tag) != "style" or _attr(st, "type") != "paragraph":
            continue
        ppr = _child(st, "pPr")
        outline = _attr(_child(ppr, "outlineLvl"), "val")
        raw[_attr(st, "styleId") or ""] = (
            (_attr(_child(st, "name"), "val") or "").lower(),
            int(outline) if outline and outline.isdigit() else None,
            _attr(_child(st, "basedOn"), "val"),
            _child(ppr, "numPr") is not None,
        )

    def level(style_id: str | None, depth: int = 0) -> int | None:
        if style_id is None or style_id not in raw or depth > 20:
            return None
        name, outline, based_on, _ = raw[style_id]
        if match := _HEADING_NAME.fullmatch(name):  # built-in names are English in every Word language
            return int(match.group(1))
        if name == "title":
            return 1
        if outline is not None:
            return outline + 1 if outline < 9 else None
        return level(based_on, depth + 1)

    return {
        sid: _Style(level(sid), toc=bool(re.fullmatch(r"toc \d", name)), list_item=has_num or name.startswith("list"))
        for sid, (name, _, _, has_num) in raw.items()
    }


def _wrapped(el: ET.Element, name: str) -> list[ET.Element]:
    """Children called ``name``, also when wrapped in content controls or custom XML."""
    out: list[ET.Element] = []
    for child in el:
        local = _local(child.tag)
        if local == name:
            out.append(child)
        elif local in ("sdt", "sdtContent", "customXml"):
            out.extend(_wrapped(child, name))
    return out


class _Word:
    def __init__(self, styles: dict[str, _Style]) -> None:
        self.styles = styles
        self.blocks: Blocks = [([], [])]
        self.path: list[str] = []
        self.headings = 0
        self.chars = 0
        self.truncated = False
        self.note_refs: dict[tuple[str, str], str] = {}  # (kind, id) -> marker, in order of appearance
        self.last_was_list = False
        self.pictures: dict[int, tuple[int, str | None]] = {}  # id(element) -> (number, alt text)

    # -- blocks
    def _add(self, text: str, list_item: bool = False) -> None:
        if self.chars > MAX_TEXT_CHARS:
            self.truncated = True
            return
        text = normalize(text)
        self.chars += len(text)
        lines = self.blocks[-1][1]
        if list_item and self.last_was_list and lines:
            lines[-1] += "\n" + text
        else:
            lines.append(text)
        self.last_was_list = list_item

    def _heading(self, level: int, text: str) -> None:
        text = " ".join(text.split())[:300]
        self.path = self.path[: level - 1] + [text]
        self.blocks.append((list(self.path), ["#" * level + " " + text]))
        self.headings += 1
        self.last_was_list = False

    # -- traversal
    def walk(self, container: ET.Element | None) -> None:
        for child in container if container is not None else []:
            name = _local(child.tag)
            if name == "p":
                self._paragraph(child)
            elif name == "tbl":
                table = self._table(child)
                if table:
                    self._add(table)
            elif name in ("sdt", "sdtContent", "customXml", "AlternateContent", "Choice", "ins", "moveTo", "smartTag"):
                self.walk(child)

    def inline(self, el: ET.Element, out: list[str], boxes: list[ET.Element]) -> None:
        for child in el:
            name = _local(child.tag)
            if name in _DOCX_SKIP:
                continue
            if name == "t":
                out.append(child.text or "")
            elif name == "tab":
                out.append("\t")
            elif name in ("br", "cr"):
                out.append("\n")
            elif name == "noBreakHyphen":
                out.append("-")
            elif name in ("footnoteReference", "endnoteReference"):
                kind = "footnote" if name.startswith("foot") else "endnote"
                key = (kind, _attr(child, "id") or "")
                if key not in self.note_refs:
                    count = sum(1 for k in self.note_refs if k[0] == kind) + 1
                    self.note_refs[key] = f"[^{count}]" if kind == "footnote" else f"[^e{count}]"
                out.append(self.note_refs[key])
            elif name == "txbxContent":
                boxes.append(child)  # text boxes become their own paragraphs after this one
            elif name in ("blip", "imagedata") and id(child) in self.pictures:
                out.append(picture_marker(*self.pictures[id(child)]))
            else:
                self.inline(child, out, boxes)

    def _paragraph_text(self, p: ET.Element) -> tuple[str, list[ET.Element]]:
        out: list[str] = []
        boxes: list[ET.Element] = []
        self.inline(p, out, boxes)
        return "".join(out).strip(), boxes

    def _paragraph(self, p: ET.Element) -> None:
        ppr = _child(p, "pPr")
        style_id = _attr(_child(ppr, "pStyle"), "val")
        style = self.styles.get(style_id or "")
        if style is None:
            match = _HEADING_ID.fullmatch(style_id or "")
            style = _Style(int(match.group(1)) if match else None)
        if style.toc:
            return
        outline = _attr(_child(ppr, "outlineLvl"), "val")
        level = int(outline) + 1 if outline and outline.isdigit() and int(outline) < 9 else style.level
        text, boxes = self._paragraph_text(p)
        if text:
            if level:
                self._heading(level, text)
            else:
                is_list = style.list_item or _child(ppr, "numPr") is not None
                self._add("- " + text if is_list else text, list_item=is_list)
        for box in boxes:
            self.walk(box)

    def _cell(self, tc: ET.Element) -> str:
        parts: list[str] = []
        for child in tc:
            name = _local(child.tag)
            if name == "p":
                text, boxes = self._paragraph_text(child)
                parts.append(text)
                parts.extend(self._cell(box) for box in boxes)
            elif name == "tbl":
                parts.append(self._table(child).replace("\n", "; "))
            elif name in ("sdt", "sdtContent", "customXml"):
                parts.append(self._cell(child))
        return " ".join(" ".join(p.split()) for p in parts if p.strip())

    def _table(self, tbl: ET.Element) -> str:
        rows: list[str] = []
        for tr in _wrapped(tbl, "tr"):  # direct rows only: nested tables are read inside their cell
            cells = [self._cell(tc) for tc in _wrapped(tr, "tc")]
            if any(cells):
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    def notes(self, package: Package, rels: dict[str, tuple[str, str]]) -> None:
        if not self.note_refs:
            return
        lines: list[str] = []
        for kind, suffix in (("footnote", "/footnotes"), ("endnote", "/endnotes")):
            root = package.xml(_target(rels, suffix))
            texts: dict[str, str] = {}
            for note in root if root is not None else []:
                if _local(note.tag) == kind:
                    paragraphs = [self._paragraph_text(p)[0] for p in note.iter() if _local(p.tag) == "p"]
                    texts[_attr(note, "id") or ""] = " ".join(p for p in paragraphs if p)
            for (k, note_id), marker in self.note_refs.items():
                if k == kind and texts.get(note_id):
                    lines.append(f"{marker}: {texts[note_id]}")
        if lines:
            self.blocks.append((["Notes"], ["# Notes", "\n".join(lines)]))


def extract_docx(package: Package, version: str) -> Result:
    main = package.main_part("docx")
    rels = package.rels(main)
    word = _Word(_docx_styles(package.xml(_target(rels, "/styles"))))
    root = package.xml(main)
    refs = _picture_refs(root, _WORD_SHAPES)
    word.pictures = {id(el): (number, alt) for number, (el, _, alt) in enumerate(refs, start=1)}
    word.walk(_child(root, "body"))
    word.notes(package, rels)
    notes = _media_note(package, "docx") + (["truncated"] if word.truncated else [])
    if not any(lines for _, lines in word.blocks):
        return Result("failed", version, error_code="no_extractable_text", notes=notes)
    all_text = "\n".join(line for _, lines in word.blocks for line in lines)
    only_pictures = not re.search(r"\w", _MARKER.sub("", all_text))
    if only_pictures:
        notes.append("pictures_only")
    if word.headings:
        sections = sections_from_blocks(word.blocks, "\n\n", preface="Start of document")
    else:  # no headings at all: numbered parts, like a plain text file
        body = normalize("\n\n".join(line for _, lines in word.blocks for line in lines))
        sections = _with_offsets([Section(0, f"Part {i + 1}", t) for i, t in enumerate(_split_long(body, 3000))])
    status = "needs_attention" if word.truncated or only_pictures else "ready"
    return Result(status, version, sections, notes=notes)


# ---------------------------------------------------------------- PowerPoint


def _collect_dml(el: ET.Element, out: list[str]) -> None:
    for child in el:
        name = _local(child.tag)
        if name in ("pPr", "rPr", "endParaRPr", "Fallback"):
            continue
        if name == "t":
            out.append(child.text or "")
        elif name == "br":
            out.append("\n")
        else:
            _collect_dml(child, out)


def _drawing_paragraphs(tx_body: ET.Element | None) -> list[str]:
    """Paragraphs of a DrawingML text body (a:p), indented by outline level."""
    lines: list[str] = []
    for p in _children(tx_body, "p"):
        out: list[str] = []
        _collect_dml(p, out)
        text = "".join(out).strip()
        if text:
            level = _attr(_child(p, "pPr"), "lvl")
            indent = "  " * int(level) if level and level.isdigit() and int(level) < 9 else ""
            lines.append(indent + text)
    return lines


def _table_rows(frame: ET.Element) -> list[str]:
    rows: list[str] = []
    for tr in frame.iter():
        if _local(tr.tag) == "tr":
            cells = [
                " ".join(" ".join(_drawing_paragraphs(_child(tc, "txBody"))).split()) for tc in _children(tr, "tc")
            ]
            if any(cells):
                rows.append(" | ".join(cells))
    return rows


def _shapes(container: ET.Element | None, found: dict[str, list[str]]) -> None:
    for shape in container if container is not None else []:
        name = _local(shape.tag)
        if name == "sp":
            ph = _child(_child(_child(shape, "nvSpPr"), "nvPr"), "ph")
            ph_type = _attr(ph, "type") if ph is not None else None
            if ph_type in ("sldNum", "dt", "ftr", "hdr", "sldImg"):
                continue  # slide number, date, footer: the same on every slide
            paragraphs = _drawing_paragraphs(_child(shape, "txBody"))
            key = "title" if ph_type in ("title", "ctrTitle") else "body"
            found[key].extend(paragraphs)
        elif name == "grpSp":
            _shapes(shape, found)
        elif name == "graphicFrame":
            found["body"].extend(_table_rows(shape))
        elif name == "AlternateContent":
            _shapes(_child(shape, "Choice"), found)


def _smartart(root: ET.Element | None) -> list[str]:
    lines: list[str] = []
    for pt in root.iter() if root is not None else []:
        if _local(pt.tag) == "pt":
            for body in _children(pt, "t"):
                lines.extend(_drawing_paragraphs(body))
    return lines


def extract_pptx(package: Package, version: str, max_pages: int) -> Result:
    slides = presentation_slides(package)
    if len(slides) > max_pages:
        return Result("failed", version, error_code="too_many_pages", page_count=len(slides))
    sections: list[Section] = []
    empty: list[int] = []
    chars = 0
    truncated = False
    for number, part in enumerate(slides, start=1):
        slide = package.xml(part)
        if slide is None:
            empty.append(number)
            continue
        slide_rels = package.rels(part)
        found: dict[str, list[str]] = {"title": [], "body": []}
        _shapes(_child(_child(slide, "cSld"), "spTree"), found)
        for typ, target in slide_rels.values():
            if typ.endswith("/diagramData"):  # SmartArt keeps its text in a separate part
                found["body"].extend(_smartart(package.xml(target)))
        notes: dict[str, list[str]] = {"title": [], "body": []}
        notes_part = _target(slide_rels, "/notesSlide")
        if notes_part:
            notes_slide = package.xml(notes_part)
            _shapes(_child(_child(notes_slide, "cSld"), "spTree") if notes_slide is not None else None, notes)
        title = " ".join(" ".join(found["title"]).split())[:300]
        slide_text = normalize("\n".join(found["body"]))
        if len(title) + len(slide_text) < MIN_PAGE_CHARS:
            empty.append(number)
        parts = [f"# {title}"] if title else []
        parts += [slide_text] if slide_text else []
        pictures = slide_pictures(package, part, slide, slide_rels)
        markers = [picture_marker(i, alt) for i, (_, alt) in enumerate(pictures, start=1)]
        parts += ["\n".join(markers)] if markers else []
        notes_text = normalize("\n".join(notes["title"] + notes["body"]))
        parts += [f"Speaker notes:\n{notes_text}"] if notes_text else []
        text = normalize("\n\n".join(parts))
        if not text:
            continue
        if chars > MAX_TEXT_CHARS:
            truncated = True
            break
        chars += len(text)
        hidden = slide.get("show") in ("0", "false")
        heading = (title + (" (hidden slide)" if hidden else "")) if title else ("(hidden slide)" if hidden else None)
        chunks = _split_long(text, MAX_SECTION_CHARS)
        for i, chunk in enumerate(chunks):
            label = f"slide {number}" if len(chunks) == 1 else f"slide {number} ({i + 1}/{len(chunks)})"
            sections.append(Section(0, label, chunk, page=number, heading=heading))
    notes_out = _media_note(package, "pptx")
    if empty:
        notes_out.append("slides_without_text:" + ",".join(map(str, empty)))
    if truncated:
        notes_out.append("truncated")
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", notes=notes_out, page_count=len(slides))
    mostly_pictures = len(empty) / max(1, len(slides)) > NEEDS_ATTENTION_EMPTY_SHARE
    status = "needs_attention" if mostly_pictures or truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes_out, page_count=len(slides))


# ---------------------------------------------------------------- Excel

_BUILTIN_DATE = {14, 15, 16, 17, 22, *range(27, 37), *range(50, 59)}
_BUILTIN_TIME = {18, 19, 20, 21, 45, 46, 47}
_CELL_REF = re.compile(r"([A-Za-z]{1,3})(\d+)")


def _format_kind(fmt_id: int, code: str | None) -> str | None:
    if code is None:
        return "date" if fmt_id in _BUILTIN_DATE else "time" if fmt_id in _BUILTIN_TIME else None
    first = code.split(";", 1)[0]
    stripped = re.sub(r'"[^"]*"|\\.|_.|\*.|\[[^\]]*\]', "", first)
    if re.search(r"[yd]", stripped, re.IGNORECASE):
        return "date"
    if re.search(r"[hs]", stripped, re.IGNORECASE):
        return "time"
    if re.search(r"m", stripped, re.IGNORECASE):
        return "date"
    return None


def _date_styles(root: ET.Element | None) -> dict[int, str]:
    custom = {
        int(f.get("numFmtId", "-1")): f.get("formatCode", "")
        for f in (_children(_child(root, "numFmts"), "numFmt") if root is not None else [])
        if (f.get("numFmtId") or "").isdigit()
    }
    out: dict[int, str] = {}
    for index, xf in enumerate(_children(_child(root, "cellXfs"), "xf") if root is not None else []):
        fmt_id = int(xf.get("numFmtId") or 0) if (xf.get("numFmtId") or "0").isdigit() else 0
        kind = _format_kind(fmt_id, custom.get(fmt_id))
        if kind:
            out[index] = kind
    return out


def _rich_text(el: ET.Element) -> str:
    out: list[str] = []

    def collect(node: ET.Element) -> None:
        for child in node:
            name = _local(child.tag)
            if name in ("rPh", "phoneticPr", "rPr"):
                continue  # phonetic guides duplicate the text
            if name == "t":
                out.append(child.text or "")
            else:
                collect(child)

    collect(el)
    return "".join(out)


def _number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return format(value, ".15g")


def _excel_date(serial: float, date1904: bool, kind: str) -> str:
    if date1904:
        base = datetime(1904, 1, 1)
    else:
        base = datetime(1899, 12, 31) if serial < 60 else datetime(1899, 12, 30)  # Excel's 29 Feb 1900
    try:
        moment = base + timedelta(days=serial)
    except (OverflowError, ValueError):
        return _number(serial)
    clock = moment.strftime("%H:%M:%S" if moment.second else "%H:%M")
    if kind == "time":
        return clock
    has_time = abs(serial - int(serial)) > 1e-9
    return moment.date().isoformat() + (f" {clock}" if has_time else "")


def _cell_value(cell: ET.Element, shared: list[str], dates: dict[int, str], date1904: bool) -> str:
    cell_type = cell.get("t", "n")
    value = _child(cell, "v")
    raw = value.text if value is not None and value.text is not None else None
    if cell_type == "inlineStr":
        inline = _child(cell, "is")
        return _rich_text(inline) if inline is not None else ""
    if raw is None:
        formula = _child(cell, "f")  # saved without a computed result (some tools do this): show the formula
        return f"={formula.text}" if formula is not None and formula.text else ""
    if cell_type == "s":
        index = int(raw) if raw.strip().isdigit() else -1
        return shared[index] if 0 <= index < len(shared) else ""
    if cell_type == "b":
        return "TRUE" if raw.strip() == "1" else "FALSE"
    if cell_type in ("str", "e", "d"):
        return raw
    try:
        number = float(raw)
    except ValueError:
        return raw
    style = cell.get("s")
    kind = dates.get(int(style)) if style and style.isdigit() else None
    return _excel_date(number, date1904, kind) if kind else _number(number)


def _column(ref: str | None) -> int | None:
    match = _CELL_REF.fullmatch(ref or "")
    if not match:
        return None
    col = 0
    for ch in match.group(1).upper():
        col = col * 26 + ord(ch) - 64
    return col


def _sheet_rows(
    data: bytes, shared: list[str], dates: dict[int, str], date1904: bool
) -> list[tuple[int, dict[int, str]]]:
    if any(marker in data for marker in _DTD_MARKERS):
        raise PackageError("unsafe_document")
    rows: list[tuple[int, dict[int, str]]] = []
    previous_row = 0
    try:
        for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
            if _local(el.tag) != "row":
                continue
            number = int(el.get("r")) if (el.get("r") or "").isdigit() else previous_row + 1
            previous_row = number
            cells: dict[int, str] = {}
            last_col = 0
            for cell in el:
                if _local(cell.tag) != "c":
                    continue
                col = _column(cell.get("r")) or last_col + 1
                last_col = col
                text = " ".join(_cell_value(cell, shared, dates, date1904).split())
                if text:
                    cells[col] = text
            if cells:
                rows.append((number, cells))
            el.clear()
    except ET.ParseError as exc:
        raise PackageError("office_unreadable") from exc
    return rows


def _sheet_section(sheet: str | None, rows: list[tuple[int, str]], header: str) -> Section:
    """Rows of one sheet; later parts refer to the first row so the columns stay readable."""
    body = "\n".join(line for _, line in rows)
    if rows[0][1] != header:
        body = f"(columns as in {header})\n{body}"
    label = f"rows {rows[0][0]}–{rows[-1][0]}"
    return Section(0, f"{sheet[:60]}, {label}" if sheet else label, body, heading=sheet[:300] if sheet else None)


def table_sections(sheet: str | None, lines: list[tuple[int, str]], chars: int) -> tuple[list[Section], int, bool]:
    """Numbered row lines cut into sections of at most MAX_SECTION_CHARS. Shared by Excel, OpenDocument
    spreadsheets and CSV. Returns the sections, the characters used so far, and whether the text cap was hit."""
    chunks: list[list[tuple[int, str]]] = [[]]
    size = 0
    truncated = False
    for number, line in lines:
        if chars > MAX_TEXT_CHARS:
            truncated = True
            break
        line = line[: MAX_SECTION_CHARS // 2]
        if chunks[-1] and size + len(line) > MAX_SECTION_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append((number, line))
        size += len(line) + 1
        chars += len(line) + 1
    return [_sheet_section(sheet, chunk, lines[0][1]) for chunk in chunks if chunk], chars, truncated


def extract_xlsx(package: Package, version: str, max_pages: int) -> Result:
    main = package.main_part("xlsx")
    rels = package.rels(main)
    workbook = package.xml(main)
    props = (
        next((el for el in workbook.iter() if _local(el.tag) == "workbookPr"), None) if workbook is not None else None
    )
    date1904 = _attr(props, "date1904") in ("1", "true")
    sheets = [
        (el.get("name") or f"Sheet {i}", el.get("state") or "visible", rels[rid][1])
        for i, el in enumerate(_children(_child(workbook, "sheets"), "sheet"), start=1)
        if (rid := _rel_id(el)) in rels
    ]
    if len(sheets) > max_pages:
        return Result("failed", version, error_code="too_many_pages", page_count=len(sheets))
    strings_root = package.xml(_target(rels, "/sharedStrings"))
    shared = [_rich_text(si) for si in _children(strings_root, "si")]
    dates = _date_styles(package.xml(_target(rels, "/styles")))
    sections: list[Section] = []
    hidden = 0
    chars = 0
    truncated = False
    for name, state, part in sheets:
        if state in ("hidden", "veryHidden"):
            hidden += 1
            continue
        data = package.read(part)
        rows = _sheet_rows(data, shared, dates, date1904) if data else []
        if not rows:
            continue
        first_col = min(min(cells) for _, cells in rows)
        lines = [
            (number, f"Row {number}: " + " | ".join(cells.get(c, "") for c in range(first_col, max(cells) + 1)))
            for number, cells in rows
        ]
        found, chars, truncated = table_sections(name, lines, chars)
        sections.extend(found)
        if truncated:
            break
    notes = _media_note(package, "xlsx")
    if hidden:
        notes.append(f"hidden_sheets:{hidden}")
    if truncated:
        notes.append("truncated")
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", notes=notes, page_count=len(sheets))
    status = "needs_attention" if truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes, page_count=len(sheets))


# ---------------------------------------------------------------- entry point


_MARKER = re.compile(r"\[picture \d+(?::[^\]]*)?\]")


def _media_note(package: Package, kind: str) -> list[str]:
    count = package.media_count(kind)
    return [f"pictures_not_extracted:{count}"] if count else []


def extract(path: Path, kind: str, max_pages: int) -> Result:
    version = f"{EXTRACTOR_VERSION}/{kind}-stdlib-2"  # -2: picture markers
    try:
        package = Package(path)
    except PackageError as exc:
        return Result("failed", version, error_code=exc.code)
    try:
        if kind == "docx":
            return extract_docx(package, version)
        if kind == "pptx":
            return extract_pptx(package, version, max_pages)
        return extract_xlsx(package, version, max_pages)
    except PackageError as exc:
        return Result("failed", version, error_code=exc.code)
    except Exception:  # noqa: BLE001 - any parser failure is reported as unreadable, never raised
        return Result("failed", version, error_code="office_unreadable")
    finally:
        package.close()
