"""which assistant the learner studies with

Additive: ``users.assistant`` (``claude``, ``codex``, ``chatgpt`` or null = not chosen yet), set on the first-run
page or in Settings (plan-without-claude.md, Phase 3). The web app names that assistant in its texts instead of
always saying "Claude". It changes no permissions: every assistant's tokens and sign-ins work as before.

Downgrade note: drops the column; the learner chooses again after an upgrade.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-21 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("assistant", sa.String(20), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_assistant"), "users", "assistant IS NULL OR assistant IN ('claude','codex','chatgpt')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_assistant"), "users", type_="check")
    op.drop_column("users", "assistant")
