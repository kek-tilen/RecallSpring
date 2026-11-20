"""Minimal OpenDocument packages for tests, built with zipfile (what LibreOffice writes, cut to the essentials)."""

from __future__ import annotations

import io
import zipfile

NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)
MIMETYPES = {
    "odt": "application/vnd.oasis.opendocument.text",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
}
BODY = {"odt": "text", "odp": "presentation", "ods": "spreadsheet"}
ENCRYPTED_MANIFEST = (
    '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
    '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml">'
    '<manifest:encryption-data manifest:checksum="x"/></manifest:file-entry></manifest:manifest>'
)


def package(
    kind: str,
    body: str,
    *,
    styles: str = "",
    files: dict[str, bytes] | None = None,
    manifest: str | None = None,
    mimetype: str | None = None,
) -> bytes:
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {NS} office:version="1.3">'
        f"<office:automatic-styles>{styles}</office:automatic-styles>"
        f"<office:body><office:{BODY[kind]}>{body}</office:{BODY[kind]}></office:body></office:document-content>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), mimetype or MIMETYPES[kind])  # stored first, uncompressed
        z.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(
            "META-INF/manifest.xml",
            manifest or '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>',
        )
        for name, data in (files or {}).items():
            z.writestr(name, data)
    return out.getvalue()


def p(text: str = "", extra: str = "") -> str:
    return f"<text:p>{text}{extra}</text:p>"


def h(text: str, level: int = 1) -> str:
    return f'<text:h text:outline-level="{level}">{text}</text:h>'


def image_frame(href: str, title: str | None = None, anchored: str = "as-char") -> str:
    alt = f"<svg:title>{title}</svg:title>" if title else ""
    return f'<draw:frame text:anchor-type="{anchored}"><draw:image xlink:href="{href}"/>{alt}</draw:frame>'


def text_frame(paragraphs: str, cls: str | None = None) -> str:
    klass = f' presentation:class="{cls}"' if cls else ""
    return f"<draw:frame{klass}><draw:text-box>{paragraphs}</draw:text-box></draw:frame>"


def slide(content: str, notes: str = "") -> str:
    spoken = (
        f'<presentation:notes><draw:frame presentation:class="notes"><draw:text-box>{p(notes)}</draw:text-box>'
        "</draw:frame></presentation:notes>"
        if notes
        else ""
    )
    return f"<draw:page>{content}{spoken}</draw:page>"


def cell(value: str = "", repeat: int = 1) -> str:
    rep = f' table:number-columns-repeated="{repeat}"' if repeat > 1 else ""
    return f"<table:table-cell{rep}>{p(value) if value else ''}</table:table-cell>"


def row(cells: str, repeat: int = 1) -> str:
    rep = f' table:number-rows-repeated="{repeat}"' if repeat > 1 else ""
    return f"<table:table-row{rep}>{cells}</table:table-row>"


def sheet(name: str, rows: str, style_name: str | None = None) -> str:
    styled = f' table:style-name="{style_name}"' if style_name else ""
    return f'<table:table table:name="{name}"{styled}>{rows}</table:table>'


HIDDEN_TABLE_STYLE = (
    '<style:style style:name="ta2" style:family="table"><style:table-properties table:display="false"/></style:style>'
)
