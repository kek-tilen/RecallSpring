"""Text-like formats: CSV/TSV tables, subtitles (SRT/WebVTT), Jupyter notebooks, source code and LaTeX.

All are read as text with the standard library and cut into citable sections. Nothing is executed, rendered or
compiled: notebook outputs are kept as the text they already contain (HTML outputs are skipped), and their
pictures are numbered ("[picture N]") so Claude can look at them with view_page. LaTeX stays LaTeX source.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
from typing import Any

from .extract import (
    _FENCE,
    _HEADING,
    EXTRACTOR_VERSION,
    MAX_SECTION_CHARS,
    MAX_TEXT_CHARS,
    PLAIN_PART_CHARS,
    Blocks,
    Result,
    Section,
    _split_long,
    _with_offsets,
    decode_text,
    normalize,
    sections_from_blocks,
)

# Source code by extension: the language is shown to Claude with every section. The file is only ever text.
CODE_LANGUAGES = {
    ".py": "Python",
    ".pyw": "Python",
    ".r": "R",
    ".jl": "Julia",
    ".m": "MATLAB/Octave",
    ".java": "Java",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".c": "C",
    ".h": "C/C++ header",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++ header",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".swift": "Swift",
    ".dart": "Dart",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (TSX)",
    ".php": "PHP",
    ".rb": "Ruby",
    ".pl": "Perl",
    ".lua": "Lua",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".fs": "F#",
    ".ex": "Elixir",
    ".erl": "Erlang",
    ".clj": "Clojure",
    ".lisp": "Lisp",
    ".scm": "Scheme",
    ".pro": "Prolog",
    ".asm": "Assembly",
    ".s": "Assembly",
    ".vhd": "VHDL",
    ".vhdl": "VHDL",
    ".v": "Verilog",
    ".sv": "SystemVerilog",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Bash",
    ".zsh": "Zsh",
    ".ps1": "PowerShell",
    ".bat": "Batch",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".xml": "XML",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "Config",
    ".dockerfile": "Dockerfile",
    ".bib": "BibTeX",
}


def decode_lenient(data: bytes) -> tuple[str, list[str]]:
    """UTF-8/UTF-16, else Windows-1250 (Central European: what Excel and older subtitle files use on Slovenian
    Windows). The fallback is reported in the notes, so wrong letters are explained, never hidden."""
    try:
        return decode_text(data), []
    except UnicodeDecodeError:
        if b"\x00" in data:
            raise
        return data.decode("cp1250", errors="replace"), ["decoded_as:windows-1250"]


def _truncate(text: str) -> tuple[str, bool]:
    return (text[:MAX_TEXT_CHARS], True) if len(text) > MAX_TEXT_CHARS else (text, False)


# ---------------------------------------------------------------- CSV / TSV


def _delimiter(text: str, tab: bool) -> str:
    if tab:
        return "\t"
    sample = "\n".join(text.split("\n", 30)[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.split("\n", 1)[0]
        return max(",;\t|", key=first.count)


def extract_csv(text: str, notes: list[str], tab: bool = False) -> Result:
    from .office import table_sections

    version = f"{EXTRACTOR_VERSION}/csv"
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    csv.field_size_limit(1_000_000)
    lines: list[tuple[int, str]] = []
    try:
        for number, row in enumerate(csv.reader(io.StringIO(text), delimiter=_delimiter(text, tab)), start=1):
            cells = [" ".join(cell.split()) for cell in row]
            while cells and not cells[-1]:
                cells.pop()
            if cells:
                lines.append((number, f"Row {number}: " + " | ".join(cells)))
    except csv.Error:
        return Result("failed", version, error_code="csv_unreadable", notes=notes)
    if not lines:
        return Result("failed", version, error_code="empty_document", notes=notes)
    sections, _, truncated = table_sections(None, lines, 0)
    notes = notes + (["truncated"] if truncated else [])
    status = "needs_attention" if truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes, page_count=len(lines))


# ---------------------------------------------------------------- subtitles (SRT, WebVTT)

_TIME = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
_TIMING = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}")
_VOICE = re.compile(r"<v(?:\.[\w.-]+)*\s+([^>]{1,80})>")
_TAG = re.compile(r"<[^>]{0,200}>")
_ASS_CODE = re.compile(r"\{\\[^}]{0,100}\}")
SUBTITLE_WINDOW_SECONDS = 300  # one section per five minutes of the recording
PARAGRAPH_GAP_SECONDS = 4


def _seconds(h: str | None, m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000


def clock_label(t: float) -> str:
    h, rest = divmod(int(t), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_cues(text: str) -> list[tuple[float, float, str | None, str]]:
    """(start, end, speaker, text) per cue. Styling and karaoke tags are dropped; lines repeated from the
    previous cue (rolling auto-captions) are kept once."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")
    cues: list[tuple[float, float, str | None, str]] = []
    previous: list[str] = []
    i = 0
    while i < len(lines):
        match = _TIMING.match(lines[i])
        i += 1
        if not match:
            continue  # cue numbers, WEBVTT header, NOTE/STYLE/REGION blocks
        g = match.groups()
        start, end = _seconds(*g[:4]), _seconds(*g[4:])
        body: list[str] = []
        while i < len(lines) and lines[i].strip() and not _TIMING.match(lines[i]):
            body.append(lines[i])
            i += 1
        if body and body[-1].strip().isdigit() and i < len(lines) and _TIMING.match(lines[i]):
            body.pop()  # the next cue's number, in a file without blank lines between cues
        speaker = None
        out: list[str] = []
        for raw in body:
            if voice := _VOICE.search(raw):
                speaker = " ".join(voice.group(1).split())
            clean = " ".join(html.unescape(_TAG.sub("", _ASS_CODE.sub("", raw))).split())
            if clean and clean not in previous:
                out.append(clean)
        previous = out or previous
        if out:
            cues.append((start, end, speaker, " ".join(out)))
    return cues


def extract_subtitles(text: str, notes: list[str]) -> Result:
    version = f"{EXTRACTOR_VERSION}/subtitles"
    cues = parse_cues(text)
    if not cues:
        return Result("failed", version, error_code="no_subtitle_cues", notes=notes)
    windows: list[list[tuple[float, float, str | None, str]]] = [[]]
    for cue in cues:
        if windows[-1] and cue[0] - windows[-1][0][0] >= SUBTITLE_WINDOW_SECONDS:
            windows.append([])
        windows[-1].append(cue)
    sections: list[Section] = []
    chars = 0
    truncated = False
    for window in windows:
        paragraphs: list[str] = []
        current: list[str] = []
        last_end, last_speaker = -1.0, None
        for start, end, speaker, words in window:
            new_paragraph = (
                not current
                or speaker != last_speaker
                or start - last_end >= PARAGRAPH_GAP_SECONDS
                or sum(map(len, current)) > 600
            )
            if new_paragraph:
                if current:
                    paragraphs.append(" ".join(current))
                who = f"{speaker}: " if speaker else ""
                current = [f"[{clock_label(start)}] {who}{words}"]
            else:
                current.append(words)
            last_end, last_speaker = end, speaker
        if current:
            paragraphs.append(" ".join(current))
        body = "\n\n".join(paragraphs)
        if chars + len(body) > MAX_TEXT_CHARS:
            truncated = True
            break
        chars += len(body)
        label = f"{clock_label(window[0][0])}–{clock_label(window[-1][1])}"
        chunks = _split_long(body, MAX_SECTION_CHARS)
        for i, chunk in enumerate(chunks):
            sections.append(Section(0, label if len(chunks) == 1 else f"{label} ({i + 1}/{len(chunks)})", chunk))
    notes = notes + (["truncated"] if truncated else [])
    status = "needs_attention" if truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes)


# ---------------------------------------------------------------- Jupyter notebooks

MAX_OUTPUT_CHARS = 2000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
NOTEBOOK_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif")


def _joined(value: Any) -> str:
    if isinstance(value, list):
        return "".join(v for v in value if isinstance(v, str))
    return value if isinstance(value, str) else ""


def notebook_cells(raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The notebook and its cells (nbformat 4). Raises ValueError for anything else."""
    notebook = json.loads(decode_text(raw))
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise ValueError("not a notebook")
    return notebook, [c for c in notebook["cells"] if isinstance(c, dict)]


def _outputs(cell: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = cell.get("outputs") if cell.get("cell_type") == "code" else None
    return [o for o in outputs if isinstance(o, dict)] if isinstance(outputs, list) else []


def output_image(output: dict[str, Any]) -> tuple[str, str] | None:
    """(mime, base64) of a picture an output carries; one per output, in a fixed order of preference."""
    data = output.get("data")
    if output.get("output_type") in ("display_data", "execute_result") and isinstance(data, dict):
        for mime in NOTEBOOK_IMAGE_TYPES:
            if mime in data:
                return mime, _joined(data[mime])
    return None


def notebook_images(cells: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Every output picture, numbered in the same order as the "[picture N]" markers in the text."""
    return [img for cell in cells for output in _outputs(cell) if (img := output_image(output))]


def _output_text(output: dict[str, Any]) -> str:
    kind = output.get("output_type")
    if kind == "stream":
        text = _joined(output.get("text"))
    elif kind in ("execute_result", "display_data"):
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        text = _joined(data.get("text/markdown") or data.get("text/plain"))  # HTML outputs are never read
    elif kind == "error":
        trace = output.get("traceback")
        lines = "\n".join(_joined(t) for t in trace) if isinstance(trace, list) else ""
        text = f"{output.get('ename', 'Error')}: {output.get('evalue', '')}\n{lines}"
    else:
        text = ""
    text = _ANSI.sub("", text).strip("\n").rstrip()  # leading spaces align printed tables
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n[output shortened]"


def extract_notebook(raw: bytes) -> Result:
    version = f"{EXTRACTOR_VERSION}/ipynb"
    try:
        notebook, cells = notebook_cells(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return Result("failed", version, error_code="notebook_unreadable")
    meta = notebook.get("metadata") if isinstance(notebook.get("metadata"), dict) else {}
    kernel = meta.get("kernelspec") if isinstance(meta.get("kernelspec"), dict) else {}
    info = meta.get("language_info") if isinstance(meta.get("language_info"), dict) else {}
    language = str(kernel.get("language") or info.get("name") or "").lower()[:20]
    blocks: Blocks = [([], [])]
    path: list[str] = []
    picture = 0
    chars = 0
    truncated = False
    for cell in cells:
        source = normalize(_joined(cell.get("source")))
        kind = cell.get("cell_type")
        lines: list[str] = []
        if kind == "markdown":
            in_fence = False
            for line in source.split("\n"):
                if _FENCE.match(line):
                    in_fence = not in_fence
                match = None if in_fence else _HEADING.match(line)
                if match:
                    level = len(match.group(1))
                    path = path[: level - 1] + [match.group(2).strip()]
                    blocks.append((list(path), [line]))
                else:
                    blocks[-1][1].append(line)
        elif kind == "code":
            if source:
                lines += [f"```{language}", source, "```"]
            for output in _outputs(cell):
                if output_image(output):
                    picture += 1
                    lines.append(f"[picture {picture}]")
                elif text := _output_text(output):
                    lines += ["Output:", text]
        elif source:  # raw cells
            lines.append(source)
        chars += sum(len(line) + 1 for line in lines) + len(source)
        if chars > MAX_TEXT_CHARS:
            truncated = True
            break
        blocks[-1][1].extend([*lines, ""])
    sections = sections_from_blocks(blocks, "\n", preface="Notebook")
    if not sections:
        return Result("failed", version, error_code="empty_document", page_count=len(cells))
    notes = ["truncated"] if truncated else []
    return Result("needs_attention" if truncated else "ready", version, sections, notes=notes, page_count=len(cells))


# ---------------------------------------------------------------- source code


def extract_code(text: str, suffix: str) -> Result:
    language = CODE_LANGUAGES.get(suffix.lower(), "Code")
    version = f"{EXTRACTOR_VERSION}/code"
    text, truncated = _truncate(text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    if not any(lines):
        return Result("failed", version, error_code="empty_document")
    sections: list[Section] = []
    start = 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and (end == start or size + len(lines[end]) + 1 <= PLAIN_PART_CHARS):
            size += len(lines[end]) + 1
            end += 1
        if end < len(lines):  # cut after a blank line in the second half, so functions stay together
            for cut in range(end, start + (end - start) // 2, -1):
                if not lines[cut - 1].strip():
                    end = cut
                    break
        chunk = "\n".join(lines[start:end]).strip("\n")
        if chunk.strip():
            parts = _split_long(chunk, MAX_SECTION_CHARS) if len(chunk) > MAX_SECTION_CHARS else [chunk]
            for i, part in enumerate(parts):
                label = f"lines {start + 1}–{end}" + (f" (part {i + 1})" if len(parts) > 1 else "")
                sections.append(Section(0, label, part, heading=f"{language} code"))
        start = end
    notes = ["truncated"] if truncated else []
    status = "needs_attention" if truncated else "ready"
    return Result(status, version, _with_offsets(sections), notes=notes, page_count=len(lines))


# ---------------------------------------------------------------- LaTeX

_LATEX_HEADING = re.compile(
    r"^\s*\\(part|chapter|section|subsection|subsubsection|paragraph|frametitle)\*?\s*(?:\[[^\]]*\])?\s*\{"
)
_LATEX_LEVEL = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "frametitle": 6,
}
_LATEX_COMMENT = re.compile(r"(?<!\\)%.*$")
_LATEX_VERBATIM = re.compile(r"\\(begin|end)\{(verbatim\*?|Verbatim|lstlisting|minted|comment)\}")
_LATEX_INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{")
_LATEX_MACRO = re.compile(r"^\s*\\(newcommand|renewcommand|providecommand|DeclareMathOperator|def|newtheorem|title)\b")


def _braced(text: str, start: int) -> str:
    """The contents of the {...} group that opens at ``start``, with nested braces."""
    depth = 0
    for i in range(start, min(len(text), start + 400)):
        if text[i] == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif text[i] == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return text[start + 1 : start + 300]


def _without_comments(lines: list[str]) -> list[str]:
    out: list[str] = []
    verbatim: str | None = None
    for line in lines:
        if verbatim:
            if verbatim != "comment":
                out.append(line)
            if (m := _LATEX_VERBATIM.search(line)) and m.group(1) == "end" and m.group(2) == verbatim:
                verbatim = None
            continue
        if (m := _LATEX_VERBATIM.search(line)) and m.group(1) == "begin":
            verbatim = m.group(2)
            if verbatim != "comment":
                out.append(line)
            continue
        stripped = _LATEX_COMMENT.sub("", line)
        if stripped.strip() or not line.strip():  # a line that held only a comment disappears
            out.append(stripped.rstrip())
    return out


def extract_latex(text: str) -> Result:
    version = f"{EXTRACTOR_VERSION}/latex"
    text, truncated = _truncate(text.replace("\r\n", "\n").replace("\r", "\n"))
    includes = len(_LATEX_INCLUDE.findall(text))
    begin = text.find("\\begin{document}")
    preamble, body = ("", text) if begin < 0 else (text[:begin], text[begin + len("\\begin{document}") :])
    body = body.split("\\end{document}", 1)[0]
    blocks: Blocks = [([], [])]
    macros = [line for line in _without_comments(preamble.split("\n")) if _LATEX_MACRO.match(line)]
    if macros:
        blocks.append((["Preamble (macros and title)"], macros))
        blocks.append(([], []))
    path: list[str] = []
    for line in _without_comments(body.split("\n")):
        match = _LATEX_HEADING.match(line)
        if match:
            level = _LATEX_LEVEL[match.group(1)]
            title = " ".join(_braced(line, match.end() - 1).split())[:200] or match.group(1)
            path = path[: level - 1] + [title]
            blocks.append((list(path), [line]))
        else:
            blocks[-1][1].append(line)
    sections = sections_from_blocks([(p, [normalize("\n".join(lines))]) for p, lines in blocks], "\n")
    if not sections:
        return Result("failed", version, error_code="empty_document")
    notes = [f"includes_not_resolved:{includes}"] if includes else []
    notes += ["truncated"] if truncated else []
    return Result("needs_attention" if truncated else "ready", version, sections, notes=notes)


# ---------------------------------------------------------------- entry point


def extract(raw: bytes, kind: str, suffix: str) -> Result:
    if kind == "notebook":
        return extract_notebook(raw)
    try:
        if kind in ("csv", "subtitles"):
            text, notes = decode_lenient(raw)
        else:
            text, notes = decode_text(raw), []
    except UnicodeDecodeError:
        return Result("failed", f"{EXTRACTOR_VERSION}/{kind}", error_code="unsupported_encoding")
    if kind == "csv":
        return extract_csv(text, notes, tab=suffix.lower() == ".tsv")
    if kind == "subtitles":
        return extract_subtitles(text, notes)
    if kind == "latex":
        return extract_latex(text)
    return extract_code(text, suffix)
