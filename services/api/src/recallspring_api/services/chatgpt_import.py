"""Moving from ChatGPT: bring conversations, attached files and custom instructions over from a ChatGPT data export.

The export (ChatGPT → Settings → Data controls → Export data) is a ZIP with ``conversations.json`` and the files
that were attached to chats. RecallSpring stages it privately, lists the conversations, and saves the ones the
learner picks word for word as Markdown sources (category "chat", origin "import") in the course and folder they
choose, with the files attached to them. Nothing is graded or marked as known on import: Claude can read the saved
chats later and propose concepts, which the learner confirms. Custom instructions and the memories ChatGPT saved
are only offered as a suggestion for the learner's study preferences; they are never applied without the learner.

Staging: ``storage_dir/imports/<user>/<import id>/`` holds ``export.zip``, ``index.json`` and ``chats/<key>.md``.
It is not part of backups (the saved sources are) and is removed when the learner discards it or after
``import_retention_days``. The export is untrusted input: sizes and counts are bounded, names are never used as
paths, nothing in it is executed, and HTML in it is never rendered.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..errors import ApiError, not_found
from ..ingest.storage import ALLOWED_EXTENSIONS, StorageError, sanitize_filename, spool, spool_bytes
from ..models import Course, User
from . import bulk
from . import folders as folder_svc
from .events import audit
from .ownership import owned
from .sources import create_source

log = logging.getLogger(__name__)

MAX_EXPORT_ENTRIES = 50_000
MAX_CONVERSATIONS = 20_000
MAX_SAVE = 200
MAX_TITLE = 200
MAX_MEMORIES = 100
PREVIEW_CHARS = 200_000
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
FILE_ID_RE = re.compile(r"^(file[-_][A-Za-z0-9]+)")
CONVERSATIONS_RE = re.compile(r"^conversations(-\d{1,4})?\.json$")
FENCED = re.compile(r"```(?:[a-zA-Z]*\n)?(.*?)```", re.S)
NOT_AN_EXPORT = (
    "This ZIP has no conversations.json, so it does not look like a ChatGPT data export. In ChatGPT open "
    "Settings → Data controls → Export data, then upload the ZIP from the email as it is."
)


# --- staging on disk ---------------------------------------------------------------------------------------------


def _user_root(user_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / "imports" / str(user_id)


def _dir(user_id: uuid.UUID, import_id: uuid.UUID) -> Path:
    return _user_root(user_id) / str(import_id)


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_index(user_id: uuid.UUID, import_id: uuid.UUID) -> dict[str, Any]:
    path = _dir(user_id, import_id) / "index.json"
    if not path.is_file():
        raise not_found("Import")
    index = json.loads(path.read_text(encoding="utf-8"))
    if _expired(index):
        raise not_found("Import")
    return index


def _expired(index: dict[str, Any]) -> bool:
    return datetime.fromisoformat(index["expires_at"]) <= clock.now()


def _remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


# --- reading conversations.json ----------------------------------------------------------------------------------


def _ts(value: Any) -> float | None:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    return ts if 0 < ts < 1e11 else None


def _when(ts: float | None, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M") if ts else "time unknown"


def _iso(ts: float | None, tz: ZoneInfo) -> str | None:
    return datetime.fromtimestamp(ts, tz).isoformat() if ts else None


def _branch(conv: dict[str, Any]) -> list[dict[str, Any]]:
    """The messages the learner saw, in order: from the current node up to the root (edits and regenerated
    answers on other branches are left out)."""
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return []
    node_id = conv.get("current_node")
    if node_id not in mapping:
        # No current node: fall back to the leaf with the latest message.
        leaves = [n for n in mapping.values() if isinstance(n, dict) and not n.get("children")]
        leaves.sort(key=lambda n: _ts((n.get("message") or {}).get("create_time")) or 0)
        node_id = leaves[-1].get("id") if leaves else None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen and len(seen) < 100_000:
        seen.add(node_id)
        node = mapping[node_id]
        if not isinstance(node, dict):
            break
        if isinstance(node.get("message"), dict):
            out.append(node["message"])
        node_id = node.get("parent")
    out.reverse()
    return out


def _asset_id(pointer: Any) -> str | None:
    if not isinstance(pointer, str) or "://" not in pointer:
        return None
    match = FILE_ID_RE.match(pointer.split("://", 1)[1])
    return match.group(1) if match else None


def _unfence(text: str) -> str:
    """Custom instructions come wrapped in an explanation and a code fence; keep only the learner's words."""
    match = FENCED.search(text)
    return (match.group(1) if match else text).strip()


def _text(message: dict[str, Any], names: dict[str, str]) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    kind = content.get("content_type")
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    if kind == "text":
        return "\n\n".join(p for p in parts if isinstance(p, str)).strip()
    if kind == "multimodal_text":
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                fid = _asset_id(part.get("asset_pointer"))
                chunks.append(f"[Image: {names.get(fid or '', 'picture')}]")
            elif isinstance(part, dict) and isinstance(part.get("text"), str):  # e.g. an audio transcription
                chunks.append(part["text"])
        return "\n\n".join(c for c in chunks if c.strip()).strip()
    if kind == "code" and isinstance(content.get("text"), str):
        return f"```{content.get('language') or ''}\n{content['text']}\n```"
    return ""


def parse_conversation(conv: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    """Title, times, the visible messages, attachments, and any custom instructions or saved memories."""
    title = re.sub(r"\s+", " ", str(conv.get("title") or "")).strip()[:MAX_TITLE] or "Untitled chat"
    messages: list[dict[str, Any]] = []
    files: dict[str, str] = {}
    instructions: dict[str, Any] | None = None
    memories: list[tuple[float, str]] = []
    branch = _branch(conv)
    for message in branch:  # attachment names first, so images can be named in the text
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        for att in meta.get("attachments") or []:
            if isinstance(att, dict) and isinstance(att.get("id"), str):
                files[att["id"]] = sanitize_filename(str(att.get("name") or att["id"]))
    for message in branch:
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        role = author.get("role")
        content = message.get("content") if isinstance(message.get("content"), dict) else {}
        ts = _ts(message.get("create_time"))
        if content.get("content_type") == "user_editable_context":
            profile = _unfence(str(content.get("user_profile") or ""))
            how = _unfence(str(content.get("user_instructions") or ""))
            if profile or how:
                instructions = {"about_you": profile, "how_to_respond": how, "ts": ts or 0}
            continue
        recipient = message.get("recipient") or "all"
        if role == "assistant" and recipient == "bio":  # ChatGPT saving a memory
            text = _text(message, files)
            if text:
                memories.append((ts or 0, text[:2000]))
            continue
        if role not in ("user", "assistant") or recipient != "all":
            continue  # system prompts, tool calls and tool output
        if meta.get("is_visually_hidden_from_conversation"):
            continue
        text = _text(message, files)
        attached = [
            files[a["id"]]
            for a in meta.get("attachments") or []
            if isinstance(a, dict) and isinstance(a.get("id"), str) and a["id"] in files
        ]
        if not text and not attached:
            continue
        messages.append({"role": role, "ts": ts, "text": text, "attached": attached})
    if not messages:
        return None
    gizmo = conv.get("gizmo_id")
    created = _ts(conv.get("create_time")) or messages[0]["ts"]
    updated = _ts(conv.get("update_time")) or messages[-1]["ts"] or created
    return {
        "title": title,
        "created": created,
        "updated": updated,
        "messages": messages,
        "project": gizmo if isinstance(gizmo, str) and gizmo.startswith("g-p-") else None,
        "files": files,
        "instructions": instructions,
        "memories": memories,
    }


def render(parsed: dict[str, Any], tz: ZoneInfo) -> str:
    """The conversation as Markdown, every message word for word under a "## You · time" or "## ChatGPT · time"
    heading (so each message can be cited on its own)."""
    n = len(parsed["messages"])
    lines = [
        f"# {parsed['title']}",
        "",
        f"Imported from a ChatGPT data export · started {_when(parsed['created'], tz)} · "
        f"{n} message{'s' if n != 1 else ''}. Saved word for word; ChatGPT's replies are not course material.",
        "",
    ]
    for m in parsed["messages"]:
        lines.append(f"## {'You' if m['role'] == 'user' else 'ChatGPT'} · {_when(m['ts'], tz)}")
        lines.append("")
        if m["text"]:
            lines.append(m["text"])
            lines.append("")
        if m["attached"]:
            lines.append(f"Attached: {', '.join(m['attached'])}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise ApiError(
            413,
            "export_too_large",
            f"conversations.json is larger than {limit // 1024**2} MB. Raise RS_MAX_IMPORT_JSON_BYTES if the "
            "server has the memory for it.",
        )
    with zf.open(info) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "export_too_large", "conversations.json is larger than it claims.")
    return data


def _conversation_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    found = [
        i
        for i in zf.infolist()
        if not i.is_dir() and CONVERSATIONS_RE.match(PurePosixPath(i.filename.replace("\\", "/")).name)
    ]
    if not found:
        return []
    top = min(len(PurePosixPath(i.filename).parts) for i in found)  # the export's own, not a copy in a subfolder
    return sorted((i for i in found if len(PurePosixPath(i.filename).parts) == top), key=lambda i: i.filename)


def _file_members(zf: zipfile.ZipFile) -> dict[str, str]:
    """Attachment id -> ZIP member, for the files ChatGPT put into the export (named "file-…" or "file_…")."""
    out: dict[str, str] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = bulk.member_parts(info.filename)
        if parts is None:
            continue
        match = FILE_ID_RE.match(parts[-1])
        if match and Path(parts[-1]).suffix.lower() in ALLOWED_EXTENSIONS:
            out.setdefault(match.group(1), info.filename)
    return out


def _member_filename(member: str, name: str) -> str:
    """The attachment's own name when it has a supported extension, else the name inside the export."""
    if Path(name).suffix.lower() in ALLOWED_EXTENSIONS:
        return name
    base = PurePosixPath(member.replace("\\", "/")).name
    match = FILE_ID_RE.match(base)
    rest = base[match.end() :].lstrip("-_") if match else base
    return sanitize_filename(rest or base)


def _key(conv: dict[str, Any], n: int, used: set[str]) -> str:
    raw = conv.get("conversation_id") or conv.get("id")
    key = raw if isinstance(raw, str) and KEY_RE.match(raw) else f"c{n}"
    while key in used:
        key = f"{key[:70]}-{n}"
    used.add(key)
    return key


# --- the steps the learner takes ---------------------------------------------------------------------------------


def stage(db: Session, user: User, stream: Any, filename: str, request_id: str) -> dict[str, Any]:
    """Keep an uploaded export privately and list its conversations. The caller commits (audit row)."""
    settings = get_settings()
    expire(db, user)
    import_id = uuid.uuid4()
    root = _dir(user.id, import_id)
    root.mkdir(parents=True, exist_ok=False)
    try:
        try:
            tmp, sha256, size = spool(stream, settings.max_import_bytes)
        except StorageError as exc:
            raise ApiError(
                413,
                "file_too_large",
                f"The export is larger than {settings.max_import_bytes // 1024**2} MB (RS_MAX_IMPORT_BYTES).",
            ) from exc
        os.replace(tmp, root / "export.zip")
        index = _build_index(user, root, filename, import_id, sha256, size)
    except BaseException:
        _remove(root)
        raise
    audit(
        db,
        actor_id=user.id,
        action="import.chatgpt_staged",
        target_type="import",
        target_id=import_id,
        details={"conversations": len(index["conversations"]), "bytes": size, "sha256": sha256},
        request_id=request_id,
    )
    return view(index)


def _build_index(user: User, root: Path, filename: str, import_id: uuid.UUID, sha256: str, size: int) -> dict[str, Any]:
    settings = get_settings()
    tz = ZoneInfo(user.timezone)
    chats = root / "chats"
    chats.mkdir()
    conversations: list[dict[str, Any]] = []
    instructions: dict[str, Any] | None = None
    memories: dict[str, float] = {}
    skipped = 0
    with bulk.open_zip(root / "export.zip", MAX_EXPORT_ENTRIES) as zf:
        members = _conversation_members(zf)
        if not members:
            raise ApiError(422, "not_a_chatgpt_export", NOT_AN_EXPORT)
        in_export = _file_members(zf)
        used: set[str] = set()
        n = 0
        for info in members:
            try:
                data = json.loads(_read_member(zf, info, settings.max_import_json_bytes))
            except (ValueError, UnicodeDecodeError) as exc:
                raise ApiError(422, "not_a_chatgpt_export", "conversations.json could not be read.") from exc
            if not isinstance(data, list):
                raise ApiError(422, "not_a_chatgpt_export", NOT_AN_EXPORT)
            for conv in data:
                n += 1
                if n > MAX_CONVERSATIONS:
                    raise ApiError(422, "too_many_conversations", f"More than {MAX_CONVERSATIONS} conversations.")
                parsed = parse_conversation(conv, tz) if isinstance(conv, dict) else None
                if parsed is None:
                    skipped += 1
                    continue
                if parsed["instructions"] and (not instructions or parsed["instructions"]["ts"] >= instructions["ts"]):
                    instructions = parsed["instructions"]
                for ts, text in parsed["memories"]:
                    memories[text] = max(ts, memories.get(text, 0))
                key = _key(conv, n, used)
                body = render(parsed, tz).encode("utf-8")
                (chats / f"{key}.md").write_bytes(body)
                files = [
                    {"id": fid, "name": name, "member": in_export.get(fid)} for fid, name in parsed["files"].items()
                ]
                conversations.append(
                    {
                        "key": key,
                        "title": parsed["title"],
                        "created": _iso(parsed["created"], tz),
                        "updated": _iso(parsed["updated"], tz),
                        "sort": parsed["updated"] or 0,
                        "messages": len(parsed["messages"]),
                        "bytes": len(body),
                        "too_large": len(body) > settings.max_text_upload_bytes,
                        "project": parsed["project"],
                        "files": files,
                        "saved": None,
                    }
                )
    conversations.sort(key=lambda c: c["sort"], reverse=True)
    now = clock.now()
    index = {
        "id": str(import_id),
        "filename": sanitize_filename(filename),
        "sha256": sha256,
        "bytes": size,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=settings.import_retention_days)).isoformat(),
        "conversations": conversations,
        "skipped": skipped,
        "instructions": (
            {"about_you": instructions["about_you"], "how_to_respond": instructions["how_to_respond"]}
            if instructions
            else None
        ),
        "memories": [t for t, _ in sorted(memories.items(), key=lambda kv: kv[1], reverse=True)][:MAX_MEMORIES],
    }
    _write_json(root / "index.json", index)
    return index


def view(index: dict[str, Any]) -> dict[str, Any]:
    projects: dict[str, int] = {}
    for c in index["conversations"]:
        if c["project"]:
            projects[c["project"]] = projects.get(c["project"], 0) + 1
    return {
        "id": index["id"],
        "filename": index["filename"],
        "bytes": index["bytes"],
        "created_at": index["created_at"],
        "expires_at": index["expires_at"],
        "skipped": index["skipped"],
        "instructions": index["instructions"],
        "memories": index["memories"],
        "projects": [{"id": p, "chats": n} for p, n in sorted(projects.items(), key=lambda kv: -kv[1])],
        "conversations": [
            {
                "key": c["key"],
                "title": c["title"],
                "created": c["created"],
                "updated": c["updated"],
                "messages": c["messages"],
                "bytes": c["bytes"],
                "too_large": c["too_large"],
                "project": c["project"],
                "files": sum(1 for f in c["files"] if f["member"]),
                "files_missing": sum(1 for f in c["files"] if not f["member"]),
                "saved": c["saved"],
            }
            for c in index["conversations"]
        ],
    }


def summary(index: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": index["id"],
        "filename": index["filename"],
        "created_at": index["created_at"],
        "expires_at": index["expires_at"],
        "conversations": len(index["conversations"]),
        "saved": sum(1 for c in index["conversations"] if c["saved"]),
    }


def list_imports(user: User) -> list[dict[str, Any]]:
    root = _user_root(user.id)
    out = []
    if root.is_dir():
        for d in root.iterdir():
            path = d / "index.json"
            try:
                index = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not _expired(index):
                out.append(summary(index))
    return sorted(out, key=lambda i: i["created_at"], reverse=True)


def get_view(user: User, import_id: uuid.UUID) -> dict[str, Any]:
    return view(_read_index(user.id, import_id))


def _conversation(index: dict[str, Any], key: str) -> dict[str, Any]:
    found = next((c for c in index["conversations"] if c["key"] == key), None) if KEY_RE.match(key) else None
    if found is None:
        raise not_found("Conversation")
    return found


def preview(user: User, import_id: uuid.UUID, key: str) -> dict[str, Any]:
    index = _read_index(user.id, import_id)
    conv = _conversation(index, key)
    text = (_dir(user.id, import_id) / "chats" / f"{conv['key']}.md").read_text(encoding="utf-8")
    return {
        "key": conv["key"],
        "title": conv["title"],
        "text": text[:PREVIEW_CHARS],
        "truncated": len(text) > PREVIEW_CHARS,
    }


def save(
    db: Session,
    user: User,
    import_id: uuid.UUID,
    *,
    keys: list[str],
    course_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    folder: str | None,
    include_files: bool,
    request_id: str,
) -> tuple[bulk.Result, dict[str, dict[str, str]]]:
    """Save the chosen conversations (and the files attached to them) into one course and folder. Returns what
    was saved and, per conversation key, where; the caller commits and then calls ``mark_saved``."""
    settings = get_settings()
    index = _read_index(user.id, import_id)
    chosen = [_conversation(index, k) for k in dict.fromkeys(keys)]
    owned(db, Course, course_id, user.id)
    target = folder_svc.resolve_path(db, user, course_id, folder, request_id, folder_id, via="import")
    target_id = target.id if target else None
    root = _dir(user.id, import_id)
    result = bulk.Result()
    saved: dict[str, dict[str, str]] = {}
    zf: zipfile.ZipFile | None = None
    try:
        for conv in chosen:
            data = (root / "chats" / f"{conv['key']}.md").read_bytes()
            if len(data) > settings.max_text_upload_bytes:
                result.skip(conv["title"], "file_too_large")
                continue
            tmp, sha256, size = spool_bytes(data)
            existing = bulk.already_there(db, user, course_id, target_id, sha256)
            if existing is not None:
                tmp.unlink(missing_ok=True)
                result.skip(conv["title"], "already_there")
                saved[conv["key"]] = {"course_id": str(course_id), "source_id": str(existing.id)}
            else:
                source = create_source(
                    db,
                    user=user,
                    course_id=course_id,
                    tmp=tmp,
                    sha256=sha256,
                    size=size,
                    filename=sanitize_filename(f"{conv['title'][:240]}.md"),
                    kind="markdown",
                    mime="text/markdown",
                    origin="import",
                    request_id=request_id,
                    category="chat",
                    folder_id=target_id,
                )
                result.imported.append(source)
                saved[conv["key"]] = {"course_id": str(course_id), "source_id": str(source.id)}
            if not include_files:
                continue
            for f in conv["files"]:
                if not f["member"]:
                    continue
                zf = zf or bulk.open_zip(root / "export.zip", MAX_EXPORT_ENTRIES)
                try:
                    info = zf.getinfo(f["member"])
                except KeyError:
                    continue
                name = _member_filename(f["member"], f["name"])
                bulk.ingest_member(
                    db,
                    user,
                    zf,
                    info,
                    filename=name,
                    course_id=course_id,
                    folder_id=target_id,
                    category="material",
                    origin="import",
                    request_id=request_id,
                    result=result,
                    label=name,
                )
    finally:
        if zf is not None:
            zf.close()
    audit(
        db,
        actor_id=user.id,
        action="import.chatgpt_saved",
        target_type="import",
        target_id=import_id,
        details={
            "course_id": str(course_id),
            "folder_id": str(target_id) if target_id else None,
            "conversations": len(saved),
            "sources": [str(s.id) for s in result.imported],
            "skipped": len(result.skipped),
        },
        request_id=request_id,
    )
    return result, saved


def mark_saved(user: User, import_id: uuid.UUID, saved: dict[str, dict[str, str]]) -> None:
    """After the commit: remember where each conversation went, so the list shows it as saved."""
    try:
        index = _read_index(user.id, import_id)
    except ApiError:
        return
    for c in index["conversations"]:
        if c["key"] in saved:
            c["saved"] = saved[c["key"]]
    _write_json(_dir(user.id, import_id) / "index.json", index)


def discard(db: Session, user: User, import_id: uuid.UUID, request_id: str) -> None:
    """Remove the staged copy; conversations already saved stay in the library."""
    index = _read_index(user.id, import_id)
    _remove(_dir(user.id, import_id))
    audit(
        db,
        actor_id=user.id,
        action="import.chatgpt_discarded",
        target_type="import",
        target_id=import_id,
        details={"saved": sum(1 for c in index["conversations"] if c["saved"])},
        request_id=request_id,
    )


def expire(db: Session, user: User | None = None) -> int:
    """Remove staged exports past their retention (all learners when ``user`` is None). The caller commits."""
    base = get_settings().storage_dir / "imports"
    roots = [_user_root(user.id)] if user else ([d for d in base.iterdir() if d.is_dir()] if base.is_dir() else [])
    removed = 0
    for root in roots:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            try:
                index = json.loads((d / "index.json").read_text(encoding="utf-8"))
                expired = _expired(index)
            except (OSError, ValueError, KeyError):
                # A staging folder without a readable index is left over from a failed upload.
                changed = datetime.fromtimestamp(d.stat().st_mtime).astimezone()
                expired = d.is_dir() and changed < clock.now() - timedelta(days=1)
                index = None
            if not expired:
                continue
            _remove(d)
            removed += 1
            try:
                actor = uuid.UUID(root.name)
                target = uuid.UUID(d.name)
            except ValueError:
                continue
            audit(
                db,
                actor_id=actor,
                action="import.chatgpt_expired",
                target_type="import",
                target_id=target,
                details={"saved": sum(1 for c in index["conversations"] if c["saved"]) if index else 0},
            )
    return removed


def expire_all() -> None:
    """Called by the worker; never raises."""
    from ..db import new_session

    try:
        with new_session() as db:
            if expire(db):
                db.commit()
    except Exception:  # pragma: no cover - housekeeping must not stop the worker
        log.exception("removing expired imports failed")


# --- study preferences -------------------------------------------------------------------------------------------

MAX_PREFERENCES = 4000


def preferences_view(user: User) -> dict[str, Any]:
    return {"text": user.study_preferences or "", "max_chars": MAX_PREFERENCES}


def set_preferences(db: Session, user: User, text: str, request_id: str) -> dict[str, Any]:
    value = text.strip() or None
    if value and len(value) > MAX_PREFERENCES:
        raise ApiError(422, "preferences_too_long", f"Keep study preferences under {MAX_PREFERENCES} characters.")
    before = user.study_preferences
    user.study_preferences = value
    audit(
        db,
        actor_id=user.id,
        action="study.preferences_changed",
        details={"from_chars": len(before or ""), "to_chars": len(value or "")},
        request_id=request_id,
    )
    return preferences_view(user)
