"""Test harness: a fresh PostgreSQL database per test run (migrated with Alembic), truncated between tests.

Requires the local dev database (infra/compose.dev.yml). Uses the URL from services/api/.env with the
database name replaced by ``recallspring_test``; override with RS_TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

API_DIR = pathlib.Path(__file__).resolve().parents[1]
TEST_DB = "recallspring_test"


def _test_url() -> str:
    from dotenv import dotenv_values
    from sqlalchemy import make_url

    base = os.environ.get("RS_TEST_DATABASE_URL") or dotenv_values(API_DIR / ".env").get("RS_DATABASE_URL")
    if not base:
        raise RuntimeError("Set RS_TEST_DATABASE_URL or create services/api/.env (see .env.example)")
    return make_url(base).set(database=TEST_DB).render_as_string(hide_password=False)


# Configure the environment before any application module reads settings.
os.environ.update(
    {
        "RS_DATABASE_URL": _test_url(),
        "RS_ENVIRONMENT": "test",
        "RS_COOKIE_SECURE": "false",
        "RS_AI_EVALUATION_PROVIDER": "mock",
        "RS_AI_QUESTION_PROVIDER": "mock",
        "RS_MOCK_AI_BEHAVIOR": "normal",
        "RS_STORAGE_DIR": tempfile.mkdtemp(prefix="recallspring-test-storage-"),
        "RS_EXTRACTION_ISOLATION": "inprocess",  # one dedicated test covers the subprocess path
        "RS_OFFICE_RENDERER": "off",  # results must not depend on LibreOffice being installed; tests fake it
        "RS_BACKUP_ENABLED": "false",  # test_backup.py turns it on with its own folder
        "RS_BACKUP_DIR": tempfile.mkdtemp(prefix="recallspring-test-backups-"),
        "RS_RUN_DIR": tempfile.mkdtemp(prefix="recallspring-test-run-"),  # the worker heartbeat (runtime.py)
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, make_url, text  # noqa: E402

from recallspring_api import clock  # noqa: E402
from recallspring_api.config import get_settings  # noqa: E402
from recallspring_api.db import get_engine, new_session  # noqa: E402
from recallspring_api.ingest.jobs import run_pending  # noqa: E402
from recallspring_api.main import create_app  # noqa: E402
from recallspring_api.models import Base, User  # noqa: E402
from recallspring_api.security import hash_password  # noqa: E402

PASSWORD = "correct horse battery staple"

BIOLOGY_MD = """# Cellular respiration

Cells release energy from glucose in several connected stages.

## Glycolysis

Glycolysis happens in the cytoplasm. One glucose molecule is split into two pyruvate molecules, with a small
net gain of ATP and NADH.

## Citric acid cycle

In the mitochondrial matrix, pyruvate is converted to acetyl-CoA, which the citric acid cycle oxidises to CO2,
producing NADH and FADH2.
"""


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


def recreate_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[str]:
    url = os.environ["RS_DATABASE_URL"]
    recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    yield url
    get_engine().dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    return get_settings()


class FrozenClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> datetime:
        self.current = self.current + timedelta(**kwargs)
        return self.current

    def set(self, value: datetime) -> None:
        self.current = value


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    fc = FrozenClock(datetime(2026, 11, 19, 16, 0, tzinfo=UTC))  # 17:00 in Europe/Ljubljana
    monkeypatch.setattr(clock, "now", fc)
    return fc


def make_user(username: str, timezone: str = "Europe/Ljubljana") -> User:
    with new_session() as db:
        user = User(username=username, password_hash=hash_password(PASSWORD), timezone=timezone)
        db.add(user)
        db.commit()
        return user


class Api:
    """Thin client that adds CSRF and Idempotency-Key headers like the real frontend does."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def login(self, username: str, password: str = PASSWORD) -> Any:
        return self.client.post("/api/v1/auth/login", json={"username": username, "password": password})

    def headers(self, key: uuid.UUID | str | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": self.client.cookies.get("rs_csrf") or "", "Idempotency-Key": str(key or uuid.uuid4())}

    def post(self, path: str, json: Any = None, key: uuid.UUID | str | None = None) -> Any:
        return self.client.post(f"/api/v1{path}", json=json, headers=self.headers(key))

    def patch(self, path: str, json: Any = None, key: uuid.UUID | str | None = None) -> Any:
        return self.client.patch(f"/api/v1{path}", json=json, headers=self.headers(key))

    def put(self, path: str, json: Any = None, key: uuid.UUID | str | None = None) -> Any:
        return self.client.put(f"/api/v1{path}", json=json, headers=self.headers(key))

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v1{path}", params=params)

    def upload(
        self, course_id: str, filename: str, content: bytes, key: str | None = None, category: str | None = None
    ) -> Any:
        headers = self.headers(key)
        data = {"course_id": course_id, **({"category": category} if category else {})}
        return self.client.post("/api/v1/sources", data=data, files={"file": (filename, content)}, headers=headers)

    def paste(self, course_id: str, text: str, title: str = "Lecture notes", fmt: str = "markdown") -> Any:
        return self.post("/sources/text", {"course_id": course_id, "title": title, "text": text, "format": fmt})

    def sections(self, source_id: str) -> list[dict[str, Any]]:
        return self.get(f"/sources/{source_id}/sections").json()["sections"]

    # ---- convenience builders
    def course_with_question(self, *, expected_points: list[str] | None = None) -> dict[str, str]:
        course = self.post("/courses", {"title": "Biology 101"}).json()
        source = self.paste(course["id"], BIOLOGY_MD).json()
        run_pending()
        section_ids = [s["id"] for s in self.sections(source["id"])]
        concept = self.post(
            f"/courses/{course['id']}/concepts",
            {
                "term": "Glycolysis",
                "definition_draft": "Glucose is split into pyruvate",
                "source_section_ids": section_ids[:2],
            },
        ).json()
        question = self.post(
            "/questions",
            {
                "course_id": course["id"],
                "concept_ids": [concept["id"]],
                "bloom_level": 4,
                "prompt": "Compare glycolysis with the citric acid cycle.",
                "expected_points": expected_points
                if expected_points is not None
                else ["glycolysis happens in the cytoplasm", "pyruvate feeds the citric acid cycle"],
                "source_refs": section_ids[:2],
            },
        ).json()
        return {
            "course_id": course["id"],
            "concept_id": concept["id"],
            "question_id": question["id"],
            "source_id": source["id"],
            "section_ids": section_ids,
        }

    def answer(
        self,
        question_id: str,
        text: str = "Glycolysis runs in the cytoplasm and makes pyruvate.",
        kind: str = "answer",
        client_request_id: str | None = None,
        key: str | None = None,
    ) -> Any:
        return self.post(
            "/attempts",
            {
                "question_id": question_id,
                "client_request_id": client_request_id or str(uuid.uuid4()),
                "kind": kind,
                "answer_text": text,
            },
            key=key,
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def owner_api(client: TestClient) -> Api:
    make_user("owner")
    api = Api(client)
    assert api.login("owner").status_code == 200
    return api


class ConnectorApi:
    def __init__(self, client: TestClient, token: str) -> None:
        self.client = client
        self.auth = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v1/connector{path}", params=params, headers=self.auth)

    def post(self, path: str, json: Any = None, key: str | None = None) -> Any:
        headers = {**self.auth, "Idempotency-Key": key or str(uuid.uuid4())}
        return self.client.post(f"/api/v1/connector{path}", json=json, headers=headers)


@pytest.fixture
def token(owner_api: Api) -> str:
    r = owner_api.post("/settings/connector/tokens", {"label": "Claude Desktop"})
    assert r.status_code == 201
    return r.json()["token"]


@pytest.fixture
def conn(token: str) -> Any:
    with TestClient(create_app()) as c:  # no session cookie: bearer token only
        yield ConnectorApi(c, token)
