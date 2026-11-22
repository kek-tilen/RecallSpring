"""Settings -> Assistants: connection status from RecallSpring's own records, and which name the wording uses."""

from __future__ import annotations

from .conftest import Api


def status(api: Api) -> dict:
    r = api.get("/settings/assistants")
    assert r.status_code == 200
    return r.json()


def by_key(s: dict) -> dict:
    return {i["key"]: i for i in s["items"]}


def test_nothing_connected_uses_the_welcome_choice(owner_api: Api) -> None:
    s = status(owner_api)
    assert [i["key"] for i in s["items"]] == ["claude", "codex", "chatgpt"]
    assert not any(i["connected"] for i in s["items"]) and s["in_use"] is None
    owner_api.client.put("/api/v1/settings/profile", json={"assistant": "codex"}, headers=owner_api.headers())
    s = status(owner_api)
    assert s["chosen"] == "codex" and s["in_use"] == "codex"


def test_one_connected_assistant_is_named_several_are_not(owner_api: Api) -> None:
    owner_api.client.put("/api/v1/settings/profile", json={"assistant": "claude"}, headers=owner_api.headers())
    codex = owner_api.post("/settings/connector/tokens", {"client": "codex"}).json()
    s = status(owner_api)
    assert by_key(s)["codex"]["connected"] and by_key(s)["codex"]["tokens"] == 1
    assert s["in_use"] == "codex"  # what is really connected wins over the welcome choice

    claude = owner_api.post("/settings/connector/tokens", {"client": "claude"}).json()
    assert status(owner_api)["in_use"] is None  # several: "your assistant"

    owner_api.post(f"/settings/connector/tokens/{claude['id']}/revoke", {})
    s = status(owner_api)
    assert not by_key(s)["claude"]["connected"] and s["in_use"] == "codex"
    owner_api.post(f"/settings/connector/tokens/{codex['id']}/revoke", {})
    assert status(owner_api)["in_use"] == "claude"  # none connected again: back to the choice


def test_last_use_comes_from_the_connector(owner_api: Api, token: str) -> None:
    from fastapi.testclient import TestClient

    from recallspring_api.main import create_app

    with TestClient(create_app()) as c:
        assert c.get("/api/v1/connector/courses", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert by_key(status(owner_api))["claude"]["last_used_at"] is not None


def test_a_mix_of_assistants(owner_api: Api) -> None:
    put = lambda body: owner_api.client.put("/api/v1/settings/profile", json=body, headers=owner_api.headers())  # noqa: E731
    r = put({"assistant": "mix", "assistant_mix": ["chatgpt", "claude"]})
    assert r.status_code == 200
    assert r.json()["assistant"] == "mix" and r.json()["assistant_mix"] == ["claude", "chatgpt"]  # fixed order
    s = status(owner_api)
    assert s["chosen"] == "mix" and s["mix"] == ["claude", "chatgpt"] and s["in_use"] is None  # "your assistant"
    assert [(i["key"], i["in_mix"]) for i in s["items"]] == [("claude", True), ("chatgpt", True), ("codex", False)]

    codex = owner_api.post("/settings/connector/tokens", {"client": "codex"}).json()
    assert status(owner_api)["in_use"] == "codex"  # what is really connected still wins
    owner_api.post(f"/settings/connector/tokens/{codex['id']}/revoke", {})

    for bad in ({"assistant": "mix"}, {"assistant": "mix", "assistant_mix": ["codex", "codex"]}):
        r = put(bad)
        assert r.status_code == 422 and r.json()["code"] == "mix_too_small"
    assert put({"assistant": "mix", "assistant_mix": ["claude", "codex", "chatgpt", "claude"]}).status_code == 422

    r = put({"assistant": "codex"})
    assert r.json()["assistant"] == "codex" and r.json()["assistant_mix"] == []  # leaving the mix clears the list
    assert status(owner_api)["mix"] == []
    assert put({"assistant": None}).json()["assistant"] is None
