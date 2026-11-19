"""Test harness: a fresh PostgreSQL database per test run (migrated with Alembic), truncated between tests.

Requires the local dev database (infra/compose.dev.yml). Uses the URL from services/api/.env with the
database name replaced by ``recallspring_test``; override with RS_TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
import pathlib
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
from recallspring_api.main import create_app  # noqa: E402
from recallspring_api.models import Base, User  # noqa: E402
from recallspring_api.security import hash_password  # noqa: E402

PASSWORD = "correct horse battery staple"


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

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v1{path}", params=params)

    # ---- convenience builders
    def course_with_question(self, *, expected_points: list[str] | None = None) -> dict[str, str]:
        course = self.post("/courses", {"title": "Biology 101"}).json()
        concept = self.post(
            f"/courses/{course['id']}/concepts",
            {"term": "Glycolysis", "definition_draft": "Glucose is split into pyruvate"},
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
                "source_refs": ["sec-1", "sec-2"],
            },
        ).json()
        return {"course_id": course["id"], "concept_id": concept["id"], "question_id": question["id"]}

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
