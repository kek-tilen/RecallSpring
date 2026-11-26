"""Set up RecallSpring for Codex (CLI, IDE extension and the Codex app share ``~/.codex/config.toml``).

``config add`` writes one clearly marked block to Codex's ``config.toml`` and touches nothing else: other settings
are kept byte for byte, a one-time backup is made, and the result is parsed before it replaces the file. The token
itself never goes into ``config.toml``; the block only names the file that holds it.

``folders`` makes one study folder per course with an ``AGENTS.md`` (what Codex or Antigravity should do there) and a
``.codex/config.toml`` that keeps Codex read-only in that folder (Codex applies it once you trust the folder).

    python -I scripts/codex_setup.py config add --python <repo>/services/mcp/.venv/Scripts/python.exe
    python -I scripts/codex_setup.py config remove
    python -I scripts/codex_setup.py config check
    python -I scripts/codex_setup.py folders --root "%USERPROFILE%/Documents/RecallSpring Study"

Standard library only (Python 3.11+ for tomllib).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

NAME = "recallspring"
BEGIN = "# >>> recallspring (added by scripts/install-codex-connector.ps1; replaced when you run it again)"
END = "# <<< recallspring"
APPROVAL_MODES = ("writes", "prompt", "auto", "approve")
MANAGED = "<!-- Written by RecallSpring (scripts/codex_setup.py). Edit freely; delete this line to keep your edits. -->"
MANAGED_TOML = "# Written by RecallSpring (scripts/codex_setup.py). Delete this line to keep your own edits."


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def default_token_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = (
        Path(base) / "RecallSpring"
        if base
        else Path.home() / ".config" / "recallspring"
    )
    return root / "codex-connector-token"


def toml_str(value: str) -> str:
    return json.dumps(
        value, ensure_ascii=False
    )  # a JSON string is a valid TOML basic string


# ---------------------------------------------------------------- config.toml


def strip_block(text: str) -> str:
    """The file without RecallSpring's block (and the blank line before it)."""
    pattern = re.compile(
        r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"[^\n]*\n?", re.DOTALL
    )
    return pattern.sub("\n", text).rstrip("\n") + ("\n" if text.strip() else "")


def block(
    python: str,
    api_url: str,
    token_file: Path,
    approval: str,
    startup: int,
    timeout: int,
) -> str:
    lines = [
        BEGIN,
        f"[mcp_servers.{NAME}]",
        f"command = {toml_str(python)}",
        'args = ["-m", "recallspring_mcp"]',
        f"startup_timeout_sec = {startup}",
        f"tool_timeout_sec = {timeout}",
        "# writes: Codex asks before any RecallSpring tool that is not read-only (recording a grade, saving a question).",
        f"default_tools_approval_mode = {toml_str(approval)}",
        "",
        f"[mcp_servers.{NAME}.env]",
        f"RS_API_URL = {toml_str(api_url)}",
        f"RS_CONNECTOR_TOKEN_FILE = {toml_str(str(token_file))}",
        END,
    ]
    return "\n".join(lines) + "\n"


def without_ours(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    servers = dict(out.get("mcp_servers") or {})
    servers.pop(NAME, None)
    if servers:
        out["mcp_servers"] = servers
    else:
        out.pop("mcp_servers", None)
    return out


def write_checked(path: Path, text: str, expected_rest: dict[str, Any]) -> None:
    parsed = tomllib.loads(text)  # raises before anything is replaced
    if without_ours(parsed) != expected_rest:
        raise RuntimeError(
            "the result would change other Codex settings; nothing was written"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-recallspring")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tomllib.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def config_command(args: argparse.Namespace) -> int:
    path: Path = args.codex_home / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        current = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"{path} is not valid TOML ({exc}); fix it in Codex first. Nothing was changed.",
            file=sys.stderr,
        )
        return 2
    present = NAME in (current.get("mcp_servers") or {})
    if args.action == "check":
        print("present" if present else "absent")
        return 0 if present else 1

    rest_text = strip_block(original)
    rest = tomllib.loads(rest_text)
    if NAME in (rest.get("mcp_servers") or {}):
        print(
            f"{path} already has an [mcp_servers.{NAME}] entry that RecallSpring did not write. Remove it (or rename "
            "it) in Codex settings, then run this again. Nothing was changed.",
            file=sys.stderr,
        )
        return 2
    if path.exists():
        backup = path.with_name(path.name + ".bak-before-recallspring")
        if not backup.exists():
            shutil.copy2(path, backup)

    if args.action == "add":
        if not args.python or not Path(args.python).is_file():
            print("--python must point to the connector's python.exe", file=sys.stderr)
            return 2
        ours = block(
            args.python,
            args.api_url,
            args.token_file,
            args.approval,
            args.startup,
            args.timeout,
        )
        new_text = (rest_text.rstrip("\n") + "\n\n" if rest_text.strip() else "") + ours
    else:
        new_text = rest_text
    try:
        write_checked(path, new_text, without_ours(rest))
    except (tomllib.TOMLDecodeError, RuntimeError) as exc:
        print(f"Could not update {path}: {exc}. Nothing was changed.", file=sys.stderr)
        return 2
    print(f"{args.action}: done ({path})")
    return 0


# ---------------------------------------------------------------- study folders

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def folder_name(title: str) -> str:
    name = _BAD.sub("-", title).strip().rstrip(". ")[:80].rstrip(". ") or "Course"
    return f"{name} (course)" if name.upper() in _RESERVED else name


COURSE_AGENTS = """{marker}
# RecallSpring: {title}

This folder is for studying the RecallSpring {kind} "{title}" (course_id `{course_id}`) with Codex or Antigravity.
Use the RecallSpring tools for everything and pass this course_id to every tool that accepts it.

- Do not run shell commands, write files or read other files on this computer for studying. Everything lives in
  RecallSpring. Only when I ask to import a file, use import_file with the path I give you.
- Read RecallSpring for the current state (get_study_context, get_study_plan) before you say anything about my
  progress, dates or simulations, also later in a chat; never from earlier messages.
- At the start of every chat call get_study_context for this course. If needs_setup is true, ask me first what I
  prepare for (1st kolokvij, 2nd kolokvij or the exam; whole course or a part), the date, from which material to
  which, whether I have an old paper, and any specifics. Show me how you map that to the material, then save it
  with set_study_target. Analyse an old paper with record_exam_profile (every topic with its points, where it is on
  the paper and the course concepts that cover it, or not_in_material), then show me a short summary and
  confirm_exam_profile only when I say it matches. Pass its source_id: first import the
  paper as past_paper in that course (import_file), or ask me to upload it, so I can open it next to the analysis.
  Say which exam each paper was for (exam). When it was for another exam than the one I prepare for, ask me
  whether its topics should count or only its style (question types, Bloom mix, length); use "style" unless I say so.
  Look at EVERY past paper of the course (past_papers in get_study_context, photos too), not only the first; several
  photos can be one paper (extra_source_ids). If it is unclear which exam or material one belongs to, ask me; leave
  one out only when I say so (skipped_papers with my reason). For every file say why it belongs to its paper
  (papers[].evidence: why, strength strong or weak); never state a weak link as a fact, ask me about each.
- When something on the paper is not in the material (a topic, or e.g. a command's flag the material never
  explains), you may look it up on the web if you can; prefer primary sources (official documentation, the
  standard, the tool's manual). Tell me it is not from my course material, give the links and why it seems to
  matter for this exam, and ask whether to add it. Only on my yes: add_web_source (learner_agreed=true),
  create_concepts from its sections, then record_exam_profile again with those concepts and ask me to confirm.
  Whenever you teach or quiz that part later, say it comes from the web.
- Why this plan: when get_study_context says explain_plan.now is true (the first session for this exam, or its
  analysis changed) and whenever I ask why, call get_plan_rationale and explain it in a few lines before we start.
  Rephrase it, but never add claims it does not contain.
- Plan the session with get_study_plan for this course. Teach material I have not studied yet first: a few pages
  at a time in the order of the material, with page citations, then open_summary_form so I summarise in my own
  words, then 2-3 short check questions (create_questions + open_answer_form).
  When a grade you record returns offer_harder (two Solid answers in a row), offer me harder questions on that
  part once; on yes ask at its level.
- Before an exam every plan item has a depth: quick (one short question), standard (one question in the exam's
  style), relearn (not solid yet in the last week: feedback and another try). When a grade you record returns
  relearn, follow its say: feedback on my gaps from the material, ask again later in the session with a varied
  question, stop at its solid_needed Solid answers or max_tries tries today. Never call a correct answer later
  in the same session mastery.
- A target's before_exam (regular reviews only, an extra review before the exam, or intense) is my choice: change
  it with update_study_target only when I clearly ask, and say it in words, never as a chance of remembering.
- Practice and simulations only for studied material: create_quiz in the style of the exam profile, then
  open_quiz. Without an exam profile use each concept's practice.next_level from get_course_outline: 3 Apply,
  then 4 Analyze, then 5 Evaluate as my answers become solid, back one level after a weak answer, then mixed.
  Mix concepts and levels in a quiz, never above practice_limit.level.
- Check first is my choice: when a new chapter or target starts, mention it once, gently. Use check_first from
  get_course_outline and create_quiz with mode diagnostic; afterwards green = known, yellow = explain only the
  gaps (I may skip the summary), red = learn it first.
- Concept-to-Clarity (C2C), when I want to explain a concept in my own words: open_explanation_form, wait, then
  get_explanation and record_explanation_feedback (correct, missing, wrong, with section IDs you read). Not a grade;
  never rewrite my explanation or write one for me.
- Explain first and open a form as the very last step of your message; write nothing after it. In Codex the form
  appears above your reply, so there: explain in one message without a form, ask me to write when I am ready, and
  open the form first in your next message with one short line after it at most.
- My next message after a form, whatever it says, means I am done: read what I saved (get_notes, get_answer,
  get_quiz_results or get_explanation) and give me the feedback without my asking.
- These tools may give you a RecallSpring link instead of a form. Give me the link and wait. When I say I am done,
  read my answer with get_answer (one question) or get_quiz_results (a simulation) and grade it with
  record_assessment(s). Never answer for me and never reveal expected points before I answered.
- When I answer in the chat instead, ask me once per chat whether answers in the chat should count. If yes, the
  question must be in RecallSpring (create_questions first), then submit_chat_answer with my words copied exactly,
  then grade it. If no, feedback in the chat only.
- When I write notes or a summary in the chat or show a photo of handwritten notes, ask whether to save them. A
  photo: transcribe it word for word (no corrections, [?] for unreadable words), show me and apply my corrections
  exactly. Then save_chat_note, only after I confirm (concept_ids only for my summary of the chunk you just taught).
- Grade 0-4 only from my saved answer, exactly by the grading_scale RecallSpring returns with it, and cite only
  section IDs you received. Mark a grade provisional when you are unsure. Pass model_name (the model you run as). Tell me the next review dates RecallSpring returns.
  Name the level in my language with what it means for my answer (e.g. Solid: everything asked is correct), never a
  bare number such as 3/4.
- End with record_session_summary. Save everything through RecallSpring, never only in the chat; when a reply
  gives feedback on my work and nothing was saved, say "Nothing was saved to RecallSpring."
- Answer in the language I write in.
"""

PLANNING_AGENTS = """{marker}
# RecallSpring: planning

This folder is for planning across all my RecallSpring courses with Codex or Antigravity. Do not teach or quiz here.

- Do not run shell commands, write files or read other files on this computer. Everything lives in RecallSpring.
  Only when I ask to import a file, use import_file with the path I give you.
- Start with list_courses, get_study_plan without course_id, and get_exam_readiness for every kolokvij or exam in
  the next two weeks. Tell me what has priority today and this week and what is at risk.
- Create courses, import material and record kolokviji and exams (set_study_target, update_study_target,
  record_exam_profile) only after showing me what you will save. Check what exists first; never add a second copy.
  After record_exam_profile show me a short summary and confirm_exam_profile only when I say it matches.
- When something on the paper is not in the material (a topic, or e.g. a command's flag the material never
  explains), you may look it up on the web if you can; prefer primary sources (official documentation, the
  standard, the tool's manual). Tell me it is not from my course material, give the links and why it seems to
  matter for this exam, and ask whether to add it. Only on my yes: add_web_source (learner_agreed=true),
  create_concepts from its sections, then record_exam_profile again with those concepts and ask me to confirm.
- When I ask why the plan is as it is, call get_plan_rationale for that exam and explain it in a few lines, never
  with claims it does not contain.
- To study a course, open its own folder next to this one.
- Answer in the language I write in.
"""

FOLDER_CONFIG = """{marker}
# Codex uses this once you trust the folder: no file writes or shell commands without asking.
sandbox_mode = "read-only"
approval_policy = "on-request"
"""


def write_managed(path: Path, text: str, marker: str) -> str:
    if path.exists() and not path.read_text(encoding="utf-8").startswith(marker):
        return "kept (your edits)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return "written"


def fetch_courses(api_url: str, token_file: Path) -> list[dict[str, Any]]:
    token = token_file.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/v1/connector/courses",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "recallspring-codex-setup",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def make_folder(root: Path, name: str, agents: str, report: list[str]) -> None:
    folder = root / name
    a = write_managed(folder / "AGENTS.md", agents, MANAGED)
    c = write_managed(
        folder / ".codex" / "config.toml",
        FOLDER_CONFIG.format(marker=MANAGED_TOML),
        MANAGED_TOML,
    )
    report.append(f"{folder}  (AGENTS.md {a}; .codex/config.toml {c})")


def folders_command(args: argparse.Namespace) -> int:
    try:
        courses = fetch_courses(args.api_url, args.token_file)
    except OSError as exc:  # URLError, HTTPError, missing token file
        detail = (
            f"HTTP {exc.code}"
            if isinstance(exc, urllib.error.HTTPError)
            else exc.__class__.__name__
        )
        print(
            f"Could not read your courses from RecallSpring ({detail}). Is it running?",
            file=sys.stderr,
        )
        return 2
    root: Path = args.root
    report: list[str] = []
    make_folder(root, "Planning", PLANNING_AGENTS.format(marker=MANAGED), report)
    used: set[str] = {"planning"}
    for c in courses:
        if c.get("status") == "archived":
            continue
        name = folder_name(c["title"])
        if name.lower() in used:
            name = f"{name} ({c['id'][:8]})"
        used.add(name.lower())
        kind = "interest" if c.get("kind") == "interest" else "course"
        text = COURSE_AGENTS.format(
            marker=MANAGED, title=c["title"], kind=kind, course_id=c["id"]
        )
        make_folder(root, name, text, report)
    print("\n".join(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_setup")
    sub = parser.add_subparsers(dest="command", required=True)
    cfg = sub.add_parser("config")
    cfg.add_argument("action", choices=["add", "remove", "check"])
    cfg.add_argument("--codex-home", type=Path, default=default_codex_home())
    cfg.add_argument(
        "--python", help="absolute path of the connector's python.exe (for add)"
    )
    cfg.add_argument("--api-url", default="http://127.0.0.1:4318")
    cfg.add_argument("--token-file", type=Path, default=default_token_file())
    cfg.add_argument("--approval", choices=APPROVAL_MODES, default="writes")
    cfg.add_argument("--startup", type=int, default=20, help="startup_timeout_sec")
    cfg.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="tool_timeout_sec (imports and page images)",
    )
    fol = sub.add_parser("folders")
    fol.add_argument(
        "--root", type=Path, default=Path.home() / "Documents" / "RecallSpring Study"
    )
    fol.add_argument("--api-url", default="http://127.0.0.1:4318")
    fol.add_argument("--token-file", type=Path, default=default_token_file())
    args = parser.parse_args(argv)
    return config_command(args) if args.command == "config" else folders_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
