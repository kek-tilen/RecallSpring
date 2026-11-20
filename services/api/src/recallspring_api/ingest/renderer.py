"""Optional: whole pages and slides of Office and OpenDocument files as images, via LibreOffice.

Text extraction never needs this. When LibreOffice is installed (found on PATH or in its usual folders, or set with
RS_OFFICE_RENDERER_PATH), Claude can look at a whole slide or page, including shapes, charts, SmartArt and vector
drawings that have no picture of their own. LibreOffice converts the file to PDF once; the PDF is cached under
storage_dir/renders by content hash and its pages are rendered by PDFium like any other PDF (visuals.py).

Guards: LibreOffice runs headless with a fresh, throwaway profile in a private temp folder (macros disabled,
untrusted links blocked), a minimal environment and a wall-clock timeout that kills the whole process tree. It
only ever opens a copy of the learner's own file. In production run it where it has no network access
(docs/08). RS_OFFICE_RENDERER=off disables it.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from ..config import get_settings

RENDERABLE = {"docx": "docx", "pptx": "pptx", "odt": "odt", "odp": "odp"}
RENDERER_VERSION = "lo1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/opt/libreoffice/program/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
# Written into the throwaway profile before LibreOffice starts.
PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""  # noqa: E501


class RenderFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def find_soffice() -> str | None:
    settings = get_settings()
    if settings.office_renderer == "off":
        return None
    if settings.office_renderer_path is not None:
        return str(settings.office_renderer_path) if settings.office_renderer_path.is_file() else None
    for name in ("soffice", "libreoffice"):
        if found := shutil.which(name):
            return found
    return next((c for c in _CANDIDATES if Path(c).is_file()), None)


def available() -> bool:
    return find_soffice() is not None


def cached_pdf(sha256: str) -> Path:
    if not _HEX64.match(sha256):
        raise ValueError("invalid digest")
    return get_settings().storage_dir / "renders" / sha256[:2] / f"{sha256}.{RENDERER_VERSION}.pdf"


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)  # noqa: S603, S607
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)


def convert(soffice: str, source: Path, kind: str, workdir: Path, timeout: int) -> Path:
    """Run LibreOffice once on a copy of ``source``; returns the PDF it wrote. Raises RenderFailure."""
    copy = workdir / f"document.{RENDERABLE[kind]}"
    shutil.copyfile(source, copy)
    profile = workdir / "profile"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text(PROFILE, encoding="utf-8")
    out = workdir / "out"
    cmd = [
        soffice,
        f"-env:UserInstallation={profile.as_uri()}",
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--norestore",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out),
        str(copy),
    ]
    env = {"HOME": str(workdir), "TMPDIR": str(workdir), "TEMP": str(workdir), "TMP": str(workdir)}
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "LANG"):
        if name in os.environ:
            env[name] = os.environ[name]
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        cmd,
        cwd=workdir,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(proc)
        raise RenderFailure("render_timeout") from exc
    pdf = out / "document.pdf"
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise RenderFailure("render_failed")
    return pdf


def to_pdf(source: Path, sha256: str, kind: str) -> Path:
    """The cached PDF of an Office/OpenDocument file, converting it on first use. Raises RenderFailure."""
    if kind not in RENDERABLE:
        raise RenderFailure("no_visuals")
    target = cached_pdf(sha256)
    if target.is_file():
        return target
    soffice = find_soffice()
    if soffice is None:
        raise RenderFailure("renderer_unavailable")
    settings = get_settings()
    tmp_root = settings.storage_dir / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=tmp_root, ignore_cleanup_errors=True) as tmp:
        pdf = convert(soffice, source, kind, Path(tmp), settings.office_render_timeout_seconds)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial")
        shutil.copyfile(pdf, partial)
        os.replace(partial, target)
    return target
