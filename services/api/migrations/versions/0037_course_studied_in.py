"""Usually studied in (2026-11-27)

Additive. ``courses.usually_studied_in``: the assistant the learner usually studies this course in (``claude``,
``codex``, ``antigravity`` or ``chatgpt``); NULL means any, so every existing course keeps today's wording. It only
decides which assistant Today's button and the tips name for the course; every connected assistant still works with
every course (no access rule).

Downgrade note: drops the column, so the choices are lost (the wording then names the assistant in use).

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-27 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("usually_studied_in", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("ck_courses_usually_studied_in"),
        "courses",
        "usually_studied_in IS NULL OR usually_studied_in IN ('claude','codex','antigravity','chatgpt')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_courses_usually_studied_in"), "courses", type_="check")
    op.drop_column("courses", "usually_studied_in")
