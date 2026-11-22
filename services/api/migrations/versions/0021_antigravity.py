"""Antigravity as an assistant

Additive: ``connector_tokens.client`` may be ``antigravity`` (Google Antigravity using RecallSpring's local MCP
connector, like Codex), and ``users.assistant`` may choose it. Its grades are labelled "Antigravity".

Downgrade note: refuses while any Antigravity token exists (its grades would otherwise look like another
assistant's); an ``antigravity`` choice becomes "not chosen" and is taken out of a mix.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-22 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_connector_tokens_client"), "connector_tokens", type_="check")
    op.create_check_constraint(
        op.f("ck_connector_tokens_client"), "connector_tokens", "client IN ('claude','codex','antigravity')"
    )
    op.drop_constraint(op.f("ck_users_assistant"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_assistant"),
        "users",
        "assistant IS NULL OR assistant IN ('claude','codex','chatgpt','antigravity','mix')",
    )


def downgrade() -> None:
    bind = op.get_bind()
    n = bind.scalar(sa.text("SELECT count(*) FROM connector_tokens WHERE client = 'antigravity'"))
    if n:
        raise RuntimeError(f"{n} connector tokens belong to Antigravity; revoke and delete them before downgrading.")
    op.execute("UPDATE users SET assistant = NULL WHERE assistant = 'antigravity'")
    op.execute("UPDATE users SET assistant_mix = assistant_mix - 'antigravity'")
    op.execute(
        "UPDATE users SET assistant = NULL, assistant_mix = '[]'::jsonb "
        "WHERE assistant = 'mix' AND jsonb_array_length(assistant_mix) < 2"
    )
    op.drop_constraint(op.f("ck_users_assistant"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_assistant"), "users", "assistant IS NULL OR assistant IN ('claude','codex','chatgpt','mix')"
    )
    op.drop_constraint(op.f("ck_connector_tokens_client"), "connector_tokens", type_="check")
    op.create_check_constraint(op.f("ck_connector_tokens_client"), "connector_tokens", "client IN ('claude','codex')")
