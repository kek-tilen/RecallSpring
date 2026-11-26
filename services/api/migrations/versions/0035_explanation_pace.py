"""Explanation pace (2026-11-26)

Additive. ``users.explanation_pace``: how the assistant explains new material by default, ``step`` (step by step),
``balanced``, ``chunks`` (larger chunks) or ``auto`` (the assistant adapts); NOT NULL, default ``auto``, so every
existing learner keeps today's behaviour. ``courses.explanation_pace``: the same choice for one course; NULL means
the learner's default. A request in a chat holds only for that conversation and is never stored unless the learner
saves it.

Downgrade note: drops both columns, so the learners' choices are lost (assistants then explain as before).

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-26 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PACES = "'step','balanced','chunks','auto'"


def upgrade() -> None:
    op.add_column("users", sa.Column("explanation_pace", sa.String(16), nullable=False, server_default="auto"))
    op.create_check_constraint(op.f("ck_users_explanation_pace"), "users", f"explanation_pace IN ({PACES})")
    op.add_column("courses", sa.Column("explanation_pace", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("ck_courses_explanation_pace"), "courses", f"explanation_pace IS NULL OR explanation_pace IN ({PACES})"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_courses_explanation_pace"), "courses", type_="check")
    op.drop_column("courses", "explanation_pace")
    op.drop_constraint(op.f("ck_users_explanation_pace"), "users", type_="check")
    op.drop_column("users", "explanation_pace")
