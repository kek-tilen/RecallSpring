"""Text extraction into citable sections. Runs in a separate, time-limited process (see jobs.py).

Run directly:  python -I -m recallspring_api.ingest.extract <pdf|markdown|text|docx|pptx|xlsx> <path> <max_pages>
Prints one JSON object on stdout. Never executes document content; scanned PDFs are reported, not guessed.
Word, PowerPoint and Excel files are read by office.py.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EXTRACTOR_VERSION = "rs-extract-1"
MAX_SECTION_CHARS = 6000
PLAIN_PART_CHARS = 3000
MIN_PAGE_CHARS = 20
NEEDS_ATTENTION_EMPTY_SHARE = 0.3

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    position: int
    citation_label: str
    text: str
    page: int | None = None
    heading: str | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass
class Result:
    status: str  # "ready" | "needs_attention" | "failed"
    parser_version: str
    sections: list[Section] = field(default_factory=list)
    error_code: str | None = None
    notes: list[str] = field(default_factory=list)
    page_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise UnicodeDecodeError("utf-8", data, 0, 1, "NUL byte in text file")
    return text


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _split_long(text: str, limit: int) -> list[str]:
    """Split at paragraph boundaries. A paragraph longer than ``limit`` (e.g. a table) is cut at a line break
    in the second half of the chunk when there is one, otherwise hard."""
    parts: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        while len(para) > limit:
            if current:
                parts.append(current)
                current = ""
            cut = para.rfind("\n", limit // 2, limit)
            cut = cut if cut > 0 else limit
            parts.append(para[:cut])
            para = para[cut:].lstrip("\n")
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > limit and current:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        parts.append(current)
    return parts


def _with_offsets(sections: list[Section]) -> list[Section]:
    offset = 0
    for i, s in enumerate(sections):
        s.position = i
        s.char_start = offset
        s.char_end = offset + len(s.text)
        offset = s.char_end + 2  # sections are joined with a blank line
    return sections


def extract_pdf(path: Path, max_pages: int) -> Result:
    import pypdf

    version = f"{EXTRACTOR_VERSION}/pypdf-{pypdf.__version__}"
    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            return Result("failed", version, error_code="pdf_encrypted")
        page_count = len(reader.pages)
        if page_count > max_pages:
            return Result("failed", version, error_code="too_many_pages", page_count=page_count)
        sections: list[Section] = []
        empty_pages: list[int] = []
        for number, page in enumerate(reader.pages, start=1):
            text = normalize(page.extract_text() or "")
            if len(text) < MIN_PAGE_CHARS:
                empty_pages.append(number)
                continue
            chunks = _split_long(text, MAX_SECTION_CHARS)
            for i, chunk in enumerate(chunks):
                label = f"p. {number}" if len(chunks) == 1 else f"p. {number} ({i + 1}/{len(chunks)})"
                sections.append(Section(0, label, chunk, page=number))
    except Exception:  # noqa: BLE001 - any parser failure is reported as unreadable, never raised
        return Result("failed", version, error_code="pdf_unreadable")
    if not sections:
        return Result("failed", version, error_code="no_extractable_text", page_count=page_count)
    notes = []
    if empty_pages:
        notes.append("pages_without_text:" + ",".join(map(str, empty_pages)))
    status = "needs_attention" if len(empty_pages) / page_count > NEEDS_ATTENTION_EMPTY_SHARE else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes, page_count=page_count)


def extract_markdown(text: str) -> Result:
    version = f"{EXTRACTOR_VERSION}/markdown"
    text = normalize(text)
    if not text:
        return Result("failed", version, error_code="empty_document")
    blocks: Blocks = [([], [])]
    path: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            level = len(match.group(1))
            path = path[: level - 1] + [match.group(2).strip()]
            blocks.append((list(path), [line]))
        else:
            blocks[-1][1].append(line)
    return Result("ready", version, sections_from_blocks(blocks, "\n"))


# (heading path, body lines) per heading; the first block holds anything before the first heading.
Blocks = list[tuple[list[str], list[str]]]


def sections_from_blocks(blocks: Blocks, joiner: str, preface: str = "Introduction") -> list[Section]:
    """One "§ Heading" section per heading (split when long); shared by Markdown and Word documents."""
    sections: list[Section] = []
    for heading_path, lines in blocks:
        body = joiner.join(lines).strip()
        if not body:
            continue
        label_base = (heading_path[-1] if heading_path else preface)[:120]
        heading = " › ".join(heading_path)[:300] or None
        chunks = _split_long(body, MAX_SECTION_CHARS)
        for i, chunk in enumerate(chunks):
            label = label_base if len(chunks) == 1 else f"{label_base} (part {i + 1})"
            sections.append(Section(0, f"§ {label}", chunk, heading=heading))
    return _with_offsets(sections)


def extract_plain(text: str) -> Result:
    version = f"{EXTRACTOR_VERSION}/text"
    text = normalize(text)
    if not text:
        return Result("failed", version, error_code="empty_document")
    parts = _split_long(text, PLAIN_PART_CHARS)
    sections = [Section(0, f"Part {i + 1}", p) for i, p in enumerate(parts)]
    return Result("ready", version, _with_offsets(sections))


def extract(path: Path, kind: str, max_pages: int) -> Result:
    if kind == "pdf":
        return extract_pdf(path, max_pages)
    if kind in ("docx", "pptx", "xlsx"):
        from . import office

        return office.extract(path, kind, max_pages)
    try:
        text = decode_text(path.read_bytes())
    except UnicodeDecodeError:
        return Result("failed", f"{EXTRACTOR_VERSION}/{kind}", error_code="unsupported_encoding")
    return extract_markdown(text) if kind == "markdown" else extract_plain(text)


MEMORY_LIMIT_BYTES = 2 * 1024**3


def _limit_memory() -> None:
    """Cap this process's address space where the OS supports it (Linux, macOS), so a hostile file fails the
    extraction instead of starving the host. On Windows the timeout and the size limits apply."""
    try:
        import resource
    except ImportError:  # Windows
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ValueError, OSError):  # pragma: no cover - already lower, or not permitted
        pass


def main(argv: list[str]) -> int:
    _limit_memory()
    kind, path, max_pages = argv[1], Path(argv[2]), int(argv[3])
    sys.stdout.write(json.dumps(extract(path, kind, max_pages).as_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main(sys.argv))
