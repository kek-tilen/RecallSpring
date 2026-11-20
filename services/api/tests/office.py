"""Small, valid Word / PowerPoint / Excel packages for tests, built from XML snippets (no Office library)."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V = "urn:schemas-microsoft-com:vml"


def _png_1px() -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\x80\x90\xa0")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


PNG_1PX = _png_1px()
EMF = b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"\x00" * 40
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT = "application/vnd.openxmlformats-officedocument."
DOCX_MAIN = CT + "wordprocessingml.document.main+xml"
PPTX_MAIN = CT + "presentationml.presentation.main+xml"
XLSX_MAIN = CT + "spreadsheetml.sheet.main+xml"


def rels(*items: tuple[str, str, str]) -> str:
    """(id, relationship type suffix, target)."""
    body = "".join(f'<Relationship Id="{i}" Type="{REL}{t}" Target="{target}"/>' for i, t, target in items)
    return f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def package(main: str, main_type: str, parts: dict[str, str | bytes]) -> bytes:
    types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        f'<Override PartName="/{main}" ContentType="{main_type}"/></Types>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels(("rId1", "officeDocument", main)))
        for name, data in parts.items():
            z.writestr(name, data)
    return out.getvalue()


# ---------------------------------------------------------------- Word


def para(text: str = "", style: str | None = None, extra: str = "", num: bool = False) -> str:
    ppr = ""
    if style or num:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        ppr += ('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if num else "") + "</w:pPr>"
    run = f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>' if text else ""
    return f"<w:p>{ppr}{run}{extra}</w:p>"


def style(style_id: str, name: str, based_on: str | None = None, outline: int | None = None) -> str:
    based = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    ppr = f'<w:pPr><w:outlineLvl w:val="{outline}"/></w:pPr>' if outline is not None else ""
    return f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/>{based}{ppr}</w:style>'


def word_picture(rid: str, descr: str | None = None, with_fallback: bool = True) -> str:
    """An inline picture as Word writes it, with the legacy VML copy in mc:Fallback (which must not count)."""
    alt = f' descr="{descr}"' if descr else ""
    drawing = (
        f'<w:drawing><wp:inline><wp:docPr id="1" name="Picture 1"{alt}/><a:graphic><a:graphicData>'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="image.png"/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill></pic:pic></a:graphicData></a:graphic>'
        "</wp:inline></w:drawing>"
    )
    if not with_fallback:
        return f"<w:r>{drawing}</w:r>"
    fallback = f'<w:pict><v:shape><v:imagedata r:id="{rid}"/></v:shape></w:pict>'
    return (
        f'<w:r><mc:AlternateContent><mc:Choice Requires="wps">{drawing}</mc:Choice>'
        f"<mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent></w:r>"
    )


def docx(
    body: str,
    styles: str = "",
    footnotes: str | None = None,
    pictures: int = 0,
    prolog: str = "",
    images: dict[str, tuple[str, bytes]] | None = None,
) -> bytes:
    """``images``: relationship id -> (file name in word/media, bytes), for word_picture(rid)."""
    doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{prolog}'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:mc="{MC}" xmlns:wp="{WP}" xmlns:a="{A}" '
        f'xmlns:pic="{PIC}" xmlns:v="{V}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    )
    parts: dict[str, str | bytes] = {
        "word/document.xml": doc,
        "word/styles.xml": f'<w:styles xmlns:w="{W}">{styles}</w:styles>',
    }
    items = [("rId1", "styles", "styles.xml")]
    if footnotes is not None:
        parts["word/footnotes.xml"] = f'<w:footnotes xmlns:w="{W}">{footnotes}</w:footnotes>'
        items.append(("rId2", "footnotes", "footnotes.xml"))
    for i in range(pictures):
        parts[f"word/media/image{i + 1}.png"] = b"\x89PNG\r\n\x1a\n"
    for rid, (name, data) in (images or {}).items():
        parts[f"word/media/{name}"] = data
        items.append((rid, "image", f"media/{name}"))
    parts["word/_rels/document.xml.rels"] = rels(*items)
    return package("word/document.xml", DOCX_MAIN, parts)


# ---------------------------------------------------------------- PowerPoint


def shape(paragraphs: list[str] | list[tuple[str, int]], placeholder: str | None = None) -> str:
    ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
    ps = ""
    for item in paragraphs:
        text, level = (item, 0) if isinstance(item, str) else item
        ppr = f'<a:pPr lvl="{level}"/>' if level else ""
        ps += f"<a:p>{ppr}<a:r><a:t>{text}</a:t></a:r></a:p>"
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr>'
        f"<p:txBody><a:bodyPr/>{ps}</p:txBody></p:sp>"
    )


def picture(rid: str | None = None, descr: str | None = None) -> str:
    alt = f' descr="{descr}"' if descr else ""
    fill = f'<p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>' if rid else ""
    return f'<p:pic><p:nvPicPr><p:cNvPr id="3" name="pic"{alt}/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>{fill}</p:pic>'


def table(rows: list[list[str]]) -> str:
    trs = "".join(
        "<a:tr>"
        + "".join(f"<a:tc><a:txBody><a:p><a:r><a:t>{c}</a:t></a:r></a:p></a:txBody></a:tc>" for c in r)
        + "</a:tr>"
        for r in rows
    )
    return (
        f"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
    )


def slide_xml(shapes: str, hidden: bool = False, root: str = "sld") -> str:
    show = ' show="0"' if hidden else ""
    tree = f"<p:cSld><p:spTree>{shapes}</p:spTree></p:cSld>"
    return f'<p:{root} xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"{show}>{tree}</p:{root}>'


def pptx(
    slides: list[str],
    order: list[int] | None = None,
    notes: dict[int, str] | None = None,
    smartart: dict[int, list[str]] | None = None,
    media: dict[int, dict[str, tuple[str, bytes]]] | None = None,
) -> bytes:
    """``slides`` are spTree contents stored as slide1.xml, slide2.xml, ...; ``order`` lists the file numbers in
    presentation order (default: file order); ``notes``/``smartart`` are keyed by file number."""
    order = order or list(range(1, len(slides) + 1))
    parts: dict[str, str | bytes] = {}
    for number, content in enumerate(slides, start=1):
        hidden = content.startswith("HIDDEN:")
        parts[f"ppt/slides/slide{number}.xml"] = slide_xml(content.removeprefix("HIDDEN:"), hidden)
        items: list[tuple[str, str, str]] = []
        if notes and number in notes:
            items.append(("rId1", "notesSlide", f"../notesSlides/notesSlide{number}.xml"))
            parts[f"ppt/notesSlides/notesSlide{number}.xml"] = slide_xml(
                shape(["Slide image"], "sldImg") + shape([notes[number]], "body") + shape(["7"], "sldNum"),
                root="notes",
            )
        if smartart and number in smartart:
            items.append(("rId2", "diagramData", f"/ppt/diagrams/data{number}.xml"))
            pts = "".join(
                f'<dgm:pt modelId="{i}"><dgm:t><a:bodyPr/><a:p><a:r><a:t>{t}</a:t></a:r></a:p></dgm:t></dgm:pt>'
                for i, t in enumerate(smartart[number])
            )
            parts[f"ppt/diagrams/data{number}.xml"] = (
                f'<dgm:dataModel xmlns:dgm="{DGM}" xmlns:a="{A}"><dgm:ptLst>{pts}</dgm:ptLst></dgm:dataModel>'
            )
        for rid, (name, data) in ((media or {}).get(number) or {}).items():
            parts[f"ppt/media/{name}"] = data
            items.append((rid, "image", f"../media/{name}"))
        items.append(("rId9", "hyperlink", "https://example.invalid/"))  # external targets must be ignored
        parts[f"ppt/slides/_rels/slide{number}.xml.rels"] = rels(*items).replace(
            'Target="https://example.invalid/"', 'Target="https://example.invalid/" TargetMode="External"'
        )
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{n + 1}"/>' for i, n in enumerate(order, start=1))
    parts["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>'
    )
    parts["ppt/_rels/presentation.xml.rels"] = rels(*[(f"rId{n + 1}", "slide", f"slides/slide{n}.xml") for n in order])
    return package("ppt/presentation.xml", PPTX_MAIN, parts)


# ---------------------------------------------------------------- Excel


def xlsx(
    sheets: list[tuple[str, str, str]],
    shared: list[str] | None = None,
    styles: str = "",
) -> bytes:
    """``sheets``: (name, state, sheetData inner XML)."""
    parts: dict[str, str | bytes] = {}
    entries = ""
    items = []
    for i, (name, state, data) in enumerate(sheets, start=1):
        entries += f'<sheet name="{name}" sheetId="{i}" state="{state}" r:id="rId{i}"/>'
        items.append((f"rId{i}", "worksheet", f"worksheets/sheet{i}.xml"))
        parts[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="{S}"><sheetData>{data}</sheetData></worksheet>'
    if shared is not None:
        sis = "".join(f"<si>{s}</si>" if s.startswith("<") else f"<si><t>{s}</t></si>" for s in shared)
        parts["xl/sharedStrings.xml"] = f'<sst xmlns="{S}">{sis}</sst>'
        items.append(("rIdS", "sharedStrings", "sharedStrings.xml"))
    if styles:
        parts["xl/styles.xml"] = f'<styleSheet xmlns="{S}">{styles}</styleSheet>'
        items.append(("rIdT", "styles", "styles.xml"))
    parts["xl/workbook.xml"] = f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{entries}</sheets></workbook>'
    parts["xl/_rels/workbook.xml.rels"] = rels(*items)
    return package("xl/workbook.xml", XLSX_MAIN, parts)
