"""a mix of assistants

Additive: ``users.assistant`` may also be ``mix``, and ``users.assistant_mix`` lists which of ``claude``, ``codex``
and ``chatgpt`` the learner studies with then (two or three; empty otherwise). Like 0018 it is wording and setup
steps only: every assistant's tokens and sign-ins work as before.

Downgrade note: a ``mix`` choice becomes "not chosen" (null) and the list is dropped; the learner chooses again.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-22 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("assistant_mix", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.drop_constraint(op.f("ck_users_assistant"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_assistant"), "users", "assistant IS NULL OR assistant IN ('claude','codex','chatgpt','mix')"
    )


def downgrade() -> None:
    op.execute("UPDATE users SET assistant = NULL WHERE assistant = 'mix'")
    op.drop_constraint(op.f("ck_users_assistant"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_assistant"), "users", "assistant IS NULL OR assistant IN ('claude','codex','chatgpt')"
    )
    op.drop_column("users", "assistant_mix")
