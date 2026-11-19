"""Tiny, valid PDFs for tests (Helvetica text pages; an empty string makes a page without text, like a scan)."""

from __future__ import annotations


def make_pdf(pages: list[str]) -> bytes:
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objs: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids ["
        + b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
        + f"] /Count {len(pages)} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for pid, text in zip(page_ids, pages, strict=True):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1") if text else b""
        objs[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {pid + 1} 0 R >>"
        ).encode()
        objs[pid + 1] = f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    size = max(objs) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
