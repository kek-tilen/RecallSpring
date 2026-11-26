r"""A separate demo RecallSpring with labelled demo data, for trying and reviewing the UI (never the learner's data).

    services\api\.venv\Scripts\python.exe scripts\demo_instance.py setup    (re)creates the demo database, seeds it
    services\api\.venv\Scripts\python.exe scripts\demo_instance.py serve    API + web app + worker on demo.localhost:4328
    services\api\.venv\Scripts\python.exe scripts\demo_instance.py status   is it running, where things are

Isolation from the learner's own RecallSpring (127.0.0.1:4318):

- database ``recallspring_demo`` on the local dev PostgreSQL: the URL of services/api/.env with only the database
  name changed (or RS_DEMO_DATABASE_URL); ``setup`` drops and recreates that one database and refuses any other name;
- uploaded files, secrets, the worker heartbeat and logs under local-data/demo/; backups and Sign in with ChatGPT
  are off; AI is simulated (mock, always labelled);
- served on 127.0.0.1:4328 and opened as http://demo.localhost:4328/ (browsers send *.localhost to this
  computer): browsers keep cookies per host name, not per port, so signing in here never replaces the session of
  the app on 127.0.0.1:4318 or localhost:4318;
- the demo account (username ``demo``) gets a generated password, written to local-data/demo/account.txt and never
  printed.

The demo data is made through the API itself with the clock moved back three weeks, so concepts are studied,
answered and graded on different days and some reviews are due now. Every course is marked "(demo)".
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
DEMO = ROOT / "local-data" / "demo"
DEMO_DB = "recallspring_demo"
BIND = "127.0.0.1"
HOST = "demo.localhost"  # its own cookies; see the module docstring
PORT = 4328
USERNAME = "demo"
ZONE = ZoneInfo("Europe/Ljubljana")


def env_file() -> Path:
    """services/api/.env of this checkout, or of the main checkout when this is a git worktree (a worktree has
    no .env of its own). Only the database URL is read from it, and never printed."""
    own = API_DIR / ".env"
    if own.exists():
        return own
    import subprocess

    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(common).parent / "services" / "api" / ".env" if common else own


def configure(web_dist: Path | None = None) -> str:
    """Point every setting at the demo before any RecallSpring module reads them. Returns the database URL."""
    from dotenv import dotenv_values
    from sqlalchemy import make_url

    base = os.environ.get("RS_DEMO_DATABASE_URL") or dotenv_values(env_file()).get(
        "RS_DATABASE_URL"
    )
    if not base:
        raise SystemExit(
            "Set RS_DEMO_DATABASE_URL or create services/api/.env (see .env.example)."
        )
    url = make_url(base).set(database=DEMO_DB)
    if url.database != DEMO_DB:  # never another database
        raise SystemExit("Refusing: the demo database must be named recallspring_demo.")
    for sub in ("storage", "secrets", "run", "logs", "backups"):
        (DEMO / sub).mkdir(parents=True, exist_ok=True)
    rendered = url.render_as_string(hide_password=False)
    os.environ.update(
        {
            "RS_DATABASE_URL": rendered,
            "RS_ENVIRONMENT": "development",
            "RS_COOKIE_SECURE": "false",
            "RS_FIRST_RUN_ENABLED": "false",
            "RS_DEFAULT_TIMEZONE": "Europe/Ljubljana",
            "RS_STORAGE_DIR": str(DEMO / "storage"),
            "RS_SECRETS_DIR": str(DEMO / "secrets"),
            "RS_RUN_DIR": str(DEMO / "run"),
            "RS_BACKUP_ENABLED": "false",
            "RS_BACKUP_DIR": str(DEMO / "backups"),
            "RS_CHATGPT_SIGNIN_ENABLED": "false",
            "RS_AI_EVALUATION_PROVIDER": "mock",
            "RS_AI_QUESTION_PROVIDER": "mock",
            "RS_WEB_DIST": str(web_dist or ROOT / "apps" / "web" / "dist"),
        }
    )
    return rendered


# ---------------------------------------------------------------------------------------------------- demo content

MEMBRANES = """# Membranes and transport

## Membrane structure

The cell membrane is a phospholipid bilayer with embedded proteins. Hydrophobic tails face inwards, so ions and
large polar molecules cannot cross without help (the fluid mosaic model).

## Passive transport

Diffusion and facilitated diffusion move substances down their concentration gradient without ATP. Channel and
carrier proteins make facilitated diffusion specific.

## Active transport

Pumps such as the sodium-potassium pump move ions against their gradient using ATP: three Na+ out and two K+ in
per cycle, which keeps the membrane potential.
"""

RESPIRATION = """# Cellular respiration

## Glycolysis

Glycolysis happens in the cytoplasm. One glucose is split into two pyruvate, with a net gain of two ATP and two
NADH.

## Citric acid cycle

In the mitochondrial matrix, acetyl-CoA is oxidised to CO2, producing NADH, FADH2 and one ATP (or GTP) per turn.

## Oxidative phosphorylation

The electron transport chain pumps protons into the intermembrane space; ATP synthase uses the gradient to make
most of the cell's ATP. Oxygen is the final electron acceptor.
"""

PHOTOSYNTHESIS = """# Photosynthesis

## Light reactions

In the thylakoid membranes, light drives water splitting, oxygen release and the production of ATP and NADPH.

## Calvin cycle

In the stroma, RuBisCO fixes CO2; ATP and NADPH from the light reactions reduce it to sugar.
"""

LINEAR = """# Linear algebra basics

## Vectors

A vector has a magnitude and a direction; vectors add component by component and can be scaled.

## Matrix multiplication

The entry (i, j) of AB is the dot product of row i of A and column j of B; AB is defined when A has as many
columns as B has rows, and in general AB differs from BA.

## Determinants

The determinant of a square matrix is the factor by which it scales areas or volumes; it is zero exactly when the
matrix is not invertible.

## Eigenvalues

An eigenvector v of A satisfies Av = λv; the eigenvalues are the roots of det(A − λI) = 0.
"""

SPANISH = """# Spanish past tenses

## Preterite and imperfect

The preterite tells completed events ("ayer comí paella"); the imperfect describes background, habits and states in
the past ("de niño comía paella los domingos").
"""


class Client:
    """The web app's way of calling the API (CSRF and Idempotency-Key headers), on an in-process TestClient."""

    def __init__(self, http: Any, token: str | None = None) -> None:
        self.http = http
        self.token = token

    def _headers(self) -> dict[str, str]:
        key = {"Idempotency-Key": str(uuid.uuid4())}
        if self.token:
            return {**key, "Authorization": f"Bearer {self.token}"}
        return {**key, "X-CSRF-Token": self.http.cookies.get("rs_csrf") or ""}

    def _url(self, path: str) -> str:
        return f"/api/v1{'/connector' if self.token else ''}{path}"

    def post(
        self, path: str, body: Any = None, ok: tuple[int, ...] = (200, 201)
    ) -> Any:
        r = self.http.post(self._url(path), json=body, headers=self._headers())
        if r.status_code not in ok:
            raise SystemExit(f"POST {path} failed ({r.status_code}): {r.text[:400]}")
        return r.json()

    def put(self, path: str, body: Any = None) -> Any:
        r = self.http.put(self._url(path), json=body, headers=self._headers())
        if r.status_code not in (200, 201):
            raise SystemExit(f"PUT {path} failed ({r.status_code}): {r.text[:400]}")
        return r.json()

    def get(self, path: str, **params: Any) -> Any:
        r = self.http.get(self._url(path), params=params, headers=self._headers())
        if r.status_code != 200:
            raise SystemExit(f"GET {path} failed ({r.status_code}): {r.text[:400]}")
        return r.json()


class Clock:
    def __init__(self) -> None:
        self.current = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.current

    def day(self, offset: int, hour: int = 17, minute: int = 0) -> datetime:
        """``offset`` days from today (learner's local date), at a local time."""
        today = datetime.now(ZONE).date()
        local = datetime.combine(
            today + timedelta(days=offset), time(hour, minute), tzinfo=ZONE
        )
        self.current = min(local.astimezone(UTC), datetime.now(UTC))
        return self.current


def seed(api: Client, conn: Client, clock: Clock) -> dict[str, int]:
    from recallspring_api.ingest.jobs import run_pending

    counts = {"answers": 0, "summaries": 0}
    today = datetime.now(ZONE).date()

    def iso(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    def material(course: str, title: str, text: str) -> list[dict[str, Any]]:
        source = api.post(
            "/sources/text",
            {"course_id": course, "title": title, "text": text, "format": "markdown"},
        )
        run_pending()
        return api.get(f"/sources/{source['id']}/sections")["sections"]

    def concepts(
        course: str, sections: list[dict[str, Any]], terms: dict[str, str]
    ) -> dict[str, str]:
        # a heading is its path, e.g. "Membranes and transport › Membrane structure"
        by_title = {
            s["heading"].split("›")[-1].strip(): s["id"]
            for s in sections
            if s.get("heading")
        }
        ids = {}
        for term, heading in terms.items():
            made = api.post(
                f"/courses/{course}/concepts",
                {"term": term, "source_section_ids": [by_title[heading]]},
            )
            ids[term] = made["id"]
        return ids

    def study(course: str, ids: list[str], title: str, text: str) -> None:
        body = {"course_id": course, "concept_ids": ids, "title": title, "text": text}
        conn.post("/learning", {**body, "client_request_id": str(uuid.uuid4())})
        counts["summaries"] += 1

    def answer(
        course: str,
        concept: str,
        prompt: str,
        text: str,
        grade: int,
        feedback: str,
        gaps: list[str] | None = None,
        strengths: list[str] | None = None,
        bloom: int = 3,
        unsure: bool = False,
        expected: list[str] | None = None,
    ) -> None:
        question = conn.post(
            "/questions",
            {
                "course_id": course,
                "questions": [
                    {
                        "concept_ids": [concept],
                        "bloom_level": bloom,
                        "prompt": prompt,
                        "expected_points": expected
                        or ["(demo) the key idea of the concept"],
                    }
                ],
                "model_name": "demo",
            },
        )["questions"][0]["id"]
        attempt = conn.post(
            "/attempts",
            {
                "question_id": question,
                "client_request_id": str(uuid.uuid4()),
                "answer_text": text,
                "captured_via": "answer_form",
                "unsure": unsure,
                "answer_seconds": 240,
            },
        )["attempt_id"]
        conn.post(
            f"/attempts/{attempt}/assessments",
            {
                "status": "final",
                "grade": grade,
                "confidence": "medium",
                "feedback": feedback,
                "gaps": gaps or [],
                "strengths": strengths or [],
                "model_name": "demo (simulated feedback)",
            },
        )
        counts["answers"] += 1

    def mcq(
        concept: str, prompt: str, options: list[str], correct: str
    ) -> dict[str, Any]:
        keys = "ABCD"
        return {
            "type": "mcq",
            "prompt": prompt,
            "concept_ids": [concept],
            "options": [{"key": keys[i], "text": t} for i, t in enumerate(options)],
            "correct_option": correct,
        }

    # ---- three weeks ago: account settings, courses and material
    clock.day(-21, 18)
    api.put("/settings/profile", {"assistant": "codex", "greeting_name": "Demo"})
    api.post("/settings/connector/tokens", {"client": "codex"})
    bio = api.post(
        "/courses",
        {"title": "Cell Biology (demo)", "description": "Labelled demo data."},
    )["id"]
    alg = api.post(
        "/courses",
        {"title": "Linear Algebra (demo)", "description": "Labelled demo data."},
    )["id"]
    spa = api.post(
        "/courses",
        {
            "title": "Spanish A2 (demo)",
            "kind": "interest",
            "description": "Order food and talk about my week.",
        },
    )["id"]
    bio_ids = concepts(
        bio,
        material(bio, "Lecture 1 · Membranes and transport", MEMBRANES),
        {
            "Membrane structure": "Membrane structure",
            "Passive transport": "Passive transport",
            "Active transport": "Active transport",
        },
    )
    bio_ids |= concepts(
        bio,
        material(bio, "Lecture 2 · Cellular respiration", RESPIRATION),
        {
            "Glycolysis": "Glycolysis",
            "Citric acid cycle": "Citric acid cycle",
            "Oxidative phosphorylation": "Oxidative phosphorylation",
        },
    )
    bio_ids |= concepts(
        bio,
        material(bio, "Lecture 3 · Photosynthesis", PHOTOSYNTHESIS),
        {"Light reactions": "Light reactions", "Calvin cycle": "Calvin cycle"},
    )
    alg_ids = concepts(
        alg,
        material(alg, "Lecture notes · Linear algebra basics", LINEAR),
        {
            t: t
            for t in ("Vectors", "Matrix multiplication", "Determinants", "Eigenvalues")
        },
    )
    spa_ids = concepts(
        spa,
        material(spa, "Grammar · Past tenses", SPANISH),
        {"Preterite vs imperfect": "Preterite and imperfect"},
    )
    conn.post(
        "/targets",
        {
            "course_id": bio,
            "kind": "kolokvij",
            "name": "Midterm 1 (demo)",
            "due_date": iso(10),
            "scope_description": "Lectures 1-3: membranes, respiration and photosynthesis.",
            "goal": "long_term",
        },
    )
    lab = conn.post(
        "/targets",
        {
            "course_id": bio,
            "kind": "other",
            "name": "Lab quiz (demo)",
            "due_date": iso(-8),
            "scope_description": "Lecture 1: membranes.",
            "goal": "exam_only",
        },
    )["id"]
    conn.post(
        "/targets",
        {
            "course_id": alg,
            "kind": "izpit",
            "name": "Exam (demo)",
            "due_date": iso(24),
            "scope_description": "The whole course.",
        },
    )

    # ---- day -20: lecture 1 studied and answered
    clock.day(-20, 17)
    study(
        bio,
        [
            bio_ids["Membrane structure"],
            bio_ids["Passive transport"],
            bio_ids["Active transport"],
        ],
        "Lecture 1 in my words",
        "The membrane is two layers of phospholipids with proteins in it. Small things diffuse through, others need "
        "channels. Pumps use ATP to push ions the other way.",
    )
    clock.day(-20, 18)
    answer(
        bio,
        bio_ids["Membrane structure"],
        "Why can ions not cross the phospholipid bilayer on their own?",
        "Because the inside of the bilayer is hydrophobic, so charged ions are repelled.",
        3,
        "Correct and well reasoned: the hydrophobic core blocks charged particles.",
        strengths=["Names the hydrophobic core"],
    )
    answer(
        bio,
        bio_ids["Passive transport"],
        "Compare simple and facilitated diffusion.",
        "Both go down the gradient. Facilitated uses proteins.",
        2,
        "Right direction, but the answer stops early.",
        gaps=[
            "Does not say that neither uses ATP",
            "No example of a channel or carrier",
        ],
    )
    answer(
        bio,
        bio_ids["Active transport"],
        "Explain how the sodium-potassium pump keeps the membrane potential.",
        "It moves sodium and potassium.",
        1,
        "Too general to show understanding yet.",
        gaps=[
            "Missing the 3 Na+ out / 2 K+ in ratio",
            "Missing that it uses ATP against the gradient",
        ],
        unsure=True,
    )

    # ---- day -15: lecture 2 part one; the lab quiz was set up then
    clock.day(-15, 16)
    study(
        bio,
        [bio_ids["Glycolysis"], bio_ids["Citric acid cycle"]],
        "Respiration, first half",
        "Glycolysis in the cytoplasm makes 2 pyruvate, 2 ATP and 2 NADH. The cycle in the matrix burns acetyl-CoA to "
        "CO2 and loads NADH and FADH2.",
    )
    clock.day(-15, 17)
    answer(
        bio,
        bio_ids["Glycolysis"],
        "Where does glycolysis happen and what is its net yield?",
        "In the cytoplasm; net 2 ATP and 2 NADH per glucose, ending with 2 pyruvate.",
        3,
        "Complete and precise.",
        strengths=["Location", "Net yield"],
    )
    answer(
        bio,
        bio_ids["Citric acid cycle"],
        "What goes into the citric acid cycle and what comes out?",
        "Acetyl-CoA goes in and CO2 comes out.",
        2,
        "The carbon part is right; the energy carriers are missing.",
        gaps=["NADH and FADH2 as the main products"],
    )

    # ---- day -12: algebra and Spanish
    clock.day(-12, 19)
    conn.post(
        "/concepts/known",
        {"concept_ids": [alg_ids["Vectors"]], "reason": "Covered in secondary school."},
    )
    study(
        alg,
        [alg_ids["Matrix multiplication"]],
        "Matrix multiplication",
        "Row times column. Only works if the inner sizes match. AB is usually not BA.",
    )
    answer(
        alg,
        alg_ids["Matrix multiplication"],
        "Give two 2×2 matrices A and B with AB ≠ BA and show the products.",
        "A = [[1,1],[0,1]], B = [[1,0],[1,1]]; AB = [[2,1],[1,1]], BA = [[1,1],[1,2]].",
        4,
        "Correct, with a well-chosen counterexample.",
        strengths=["Correct products", "Clear counterexample"],
        bloom=4,
    )
    study(
        spa,
        [spa_ids["Preterite vs imperfect"]],
        "Past tenses",
        "Preterite = finished action. Imperfect = background, habits.",
    )
    answer(
        spa,
        spa_ids["Preterite vs imperfect"],
        "Translate and explain the tenses: 'When I was a child, I went to the beach every summer.'",
        "Cuando era niño, fui a la playa cada verano.",
        2,
        "The first verb is right; a habit needs the imperfect (iba).",
        gaps=["Habits in the past use the imperfect"],
    )

    # ---- day -9: reviews; the lab quiz passed
    clock.day(-9, 18)
    answer(
        bio,
        bio_ids["Passive transport"],
        "Why does facilitated diffusion stop speeding up at high concentrations?",
        "Because the carrier proteins are all busy (saturated), and it still needs no ATP.",
        3,
        "Correct: saturation of the carriers.",
        strengths=["Saturation"],
        bloom=4,
    )
    clock.day(-7, 12)
    conn.post(f"/targets/{lab}/update", {"status": "passed", "result": "8/10"})

    # ---- day -6: lecture 2 part two
    clock.day(-6, 17)
    study(
        bio,
        [bio_ids["Oxidative phosphorylation"]],
        "Electron transport chain",
        "Electrons go down the chain, protons get pumped out, ATP synthase lets them back in and makes ATP. O2 at the "
        "end.",
    )
    answer(
        bio,
        bio_ids["Oxidative phosphorylation"],
        "Explain why oxidative phosphorylation stops without oxygen.",
        "Without oxygen there is nothing to take the electrons at the end, so the chain stops.",
        2,
        "The key idea is there; the link to the proton gradient and ATP synthase is missing.",
        gaps=["No proton gradient, so ATP synthase stops"],
        bloom=4,
    )

    # ---- focus blocks in the last week
    for offset, course, minutes in (
        (-5, bio, 45),
        (-3, bio, 45),
        (-2, alg, 30),
        (-1, bio, 45),
    ):
        end = clock.day(offset, 19)
        clock.current = datetime.now(UTC)  # a block may be saved up to 7 days later
        api.post(
            "/focus-sessions",
            {
                "client_session_id": str(uuid.uuid4()),
                "course_id": course,
                "started_at": (end - timedelta(minutes=minutes + 5)).isoformat(),
                "ended_at": end.isoformat(),
                "planned_minutes": minutes,
                "focused_seconds": minutes * 60,
                "completed": True,
            },
        )

    # ---- day -3: a simulation, then a retake of the missed questions the same day (practice only)
    clock.day(-3, 18)
    items = [
        mcq(
            bio_ids["Membrane structure"],
            "Which part of the membrane blocks ions?",
            [
                "The hydrophobic core",
                "The glycocalyx",
                "Cholesterol only",
                "The cell wall",
            ],
            "A",
        ),
        mcq(
            bio_ids["Active transport"],
            "How many Na+ ions does the pump move out per cycle?",
            ["One", "Two", "Three", "Four"],
            "C",
        ),
        mcq(
            bio_ids["Glycolysis"],
            "What is the net ATP yield of glycolysis per glucose?",
            ["1", "2", "4", "36"],
            "B",
        ),
        mcq(
            bio_ids["Citric acid cycle"],
            "Where does the citric acid cycle run?",
            ["Cytoplasm", "Mitochondrial matrix", "Intermembrane space", "Nucleus"],
            "B",
        ),
    ]
    quiz = conn.post(
        "/quizzes",
        {
            "course_id": bio,
            "title": "Midterm 1 practice (demo)",
            "time_limit_minutes": 20,
            "items": items,
        },
    )["quiz_id"]
    questions = [i["question_id"] for i in conn.get(f"/quizzes/{quiz}")["items"]]
    picks = ["A", "B", "B", "A"]  # two right, two wrong
    clock.day(-3, 18, 20)
    conn.post(
        f"/quizzes/{quiz}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [
                {"question_id": q, "option": o}
                for q, o in zip(questions, picks, strict=True)
            ],
        },
    )
    retake = conn.post(f"/quizzes/{quiz}/retake", {"scope": "not_full"})["quiz_id"]
    again = [i["question_id"] for i in conn.get(f"/quizzes/{retake}")["items"]]
    clock.day(-3, 19)
    conn.post(
        f"/quizzes/{retake}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [{"question_id": q, "option": "C"} for q in again],
        },
    )

    # ---- yesterday: a note of the learner's own
    clock.day(-1, 20)
    api.post(
        "/notes",
        {
            "course_id": bio,
            "client_note_id": str(uuid.uuid4()),
            "title": "Questions for the tutorial",
            "body": "- Why exactly 3 Na+ and 2 K+?\n- Does FADH2 give less ATP than NADH? Why?\n",
        },
    )
    return counts


# ---------------------------------------------------------------------------------------------------- commands


def setup() -> int:
    url = configure()
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, make_url, text

    target = make_url(url)
    assert target.database == DEMO_DB
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{DEMO_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{DEMO_DB}"'))
    admin.dispose()
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")

    from fastapi.testclient import TestClient
    from recallspring_api import clock as rs_clock
    from recallspring_api.db import new_session
    from recallspring_api.main import create_app
    from recallspring_api.models import User
    from recallspring_api.security import hash_password
    from recallspring_api.services.events import audit

    password = secrets.token_urlsafe(18)
    with new_session() as db:
        user = User(
            username=USERNAME,
            password_hash=hash_password(password),
            timezone="Europe/Ljubljana",
        )
        db.add(user)
        db.flush()
        audit(
            db,
            actor_id=user.id,
            action="user.created",
            target_type="user",
            target_id=user.id,
        )
        db.commit()
    (DEMO / "account.txt").write_text(
        f"Demo RecallSpring: http://{HOST}:{PORT}/\nusername: {USERNAME}\npassword: {password}\n"
        "Labelled demo data only. Recreated by scripts/demo_instance.py setup.\n",
        encoding="utf-8",
    )

    fake = Clock()
    real_now = rs_clock.now
    rs_clock.now = fake  # type: ignore[assignment]
    try:
        with TestClient(create_app()) as http:
            login = http.post(
                "/api/v1/auth/login", json={"username": USERNAME, "password": password}
            )
            if login.status_code != 200:
                raise SystemExit(f"Demo sign-in failed ({login.status_code}).")
            api = Client(http)
            fake.day(-21, 18)
            token = api.post(
                "/settings/connector/tokens",
                {"client": "claude", "label": "Demo seeding"},
            )["token"]
            with TestClient(create_app()) as bare:
                counts = seed(api, Client(bare, token), fake)
            revoke = [
                t
                for t in api.get("/settings/connector")["tokens"]
                if t["label"] == "Demo seeding"
            ]
            for t in revoke:
                api.post(f"/settings/connector/tokens/{t['id']}/revoke")
    finally:
        rs_clock.now = real_now  # type: ignore[assignment]
    print(
        f"Demo database {DEMO_DB} ready: 3 courses, {counts['summaries']} summaries, {counts['answers']} answers."
    )
    print(f"Account: username {USERNAME!r}; the password is in {DEMO / 'account.txt'}")
    print(
        f"Start it with: services\\api\\.venv\\Scripts\\python.exe scripts\\demo_instance.py serve  ->  http://{HOST}:{PORT}/"
    )
    return 0


def serve(web_dist: Path | None) -> int:
    configure(web_dist)
    import uvicorn
    from recallspring_api import runtime
    from recallspring_api.ingest.jobs import run_worker

    runtime.log_to_file(DEMO / "logs" / "demo.log")
    threading.Thread(target=run_worker, name="demo-worker", daemon=True).start()
    print(
        f"Demo RecallSpring on http://{HOST}:{PORT}/ (logs: {DEMO / 'logs' / 'demo.log'})",
        flush=True,
    )
    uvicorn.run("recallspring_api.main:app", host=BIND, port=PORT, log_config=None)
    return 0


def status() -> int:
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://{BIND}:{PORT}/api/v1/health/ready", timeout=5
        ) as r:
            print(f"Running on http://{HOST}:{PORT}/: {r.read().decode()[:200]}")
    except OSError:
        print(f"Not running on http://{HOST}:{PORT}/")
    print(
        f"Account file: {DEMO / 'account.txt'} ({'present' if (DEMO / 'account.txt').exists() else 'missing'})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_instance", description=__doc__.split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="drop and recreate the demo database, then seed it")
    s = sub.add_parser(
        "serve", help=f"run the demo on http://{HOST}:{PORT}/ (API, web app and worker)"
    )
    s.add_argument(
        "--web-dist",
        type=Path,
        help="a built web app to serve (default: apps/web/dist of this checkout)",
    )
    sub.add_parser("status", help="is the demo running")
    args = parser.parse_args(argv)
    if args.command == "setup":
        return setup()
    if args.command == "serve":
        return serve(args.web_dist)
    return status()


if __name__ == "__main__":
    sys.exit(main())
