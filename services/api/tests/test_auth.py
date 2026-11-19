"""Owner authentication, CSRF and idempotency enforcement."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from .conftest import Api, make_user


def test_login_sets_httponly_session_and_readable_csrf_cookie(client: TestClient) -> None:
    make_user("owner")
    r = Api(client).login("owner")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "owner"
    set_cookie = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("rs_session="))
    csrf_cookie = next(c for c in set_cookie if c.startswith("rs_csrf="))
    assert "HttpOnly" in session_cookie and "SameSite=strict" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_wrong_password_is_rejected_and_rate_limited(client: TestClient) -> None:
    make_user("owner")
    api = Api(client)
    for _ in range(5):
        r = api.login("owner", "wrong password")
        assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    assert api.login("owner").status_code == 429  # even the right password is blocked for the window


def test_unknown_user_gets_the_same_error(client: TestClient) -> None:
    r = Api(client).login("nobody", "whatever")
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"


def test_requests_without_session_are_unauthenticated(client: TestClient) -> None:
    r = client.get("/api/v1/courses")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "not_authenticated" and body["request_id"]


def test_writes_require_csrf_token(owner_api: Api) -> None:
    r = owner_api.client.post("/api/v1/courses", json={"title": "X"}, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"


def test_writes_require_idempotency_key(owner_api: Api) -> None:
    r = owner_api.client.post(
        "/api/v1/courses", json={"title": "X"}, headers={"X-CSRF-Token": owner_api.client.cookies.get("rs_csrf")}
    )
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"


def test_idempotent_replay_returns_same_body_and_reuse_with_other_body_fails(owner_api: Api) -> None:
    key = uuid.uuid4()
    first = owner_api.post("/courses", {"title": "Chemistry"}, key=key)
    again = owner_api.post("/courses", {"title": "Chemistry"}, key=key)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() and again.headers["Idempotent-Replay"] == "true"
    assert len(owner_api.get("/courses").json()) == 1
    other = owner_api.post("/courses", {"title": "Physics"}, key=key)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"


def test_logout_revokes_the_session(owner_api: Api) -> None:
    r = owner_api.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": owner_api.client.cookies.get("rs_csrf")})
    assert r.status_code == 204
    assert owner_api.get("/courses").status_code == 401


def test_validation_errors_do_not_echo_submitted_values(owner_api: Api) -> None:
    secret_text = "my private note that must not be echoed"
    r = owner_api.post("/courses", {"title": secret_text * 20})
    assert r.status_code == 422
    assert secret_text not in r.text
