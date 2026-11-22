"""Check first and a practice limit

Additive (owner decisions 2026-11-22):

* ``courses.bloom_ceiling``: the highest Bloom level (2-5) the learner wants to practise in this course; NULL means
  no limit (5). ``courses.bloom_ceiling_confirmed_at``: when the learner kept the limit although an exam profile of
  the course asks for higher levels.
* ``attempts.guessing``: the learner marked a closed answer (multiple choice, true/false) as a guess. Part of the
  raw answer, saved with it before any grading.

Downgrade drops the three columns (the limit and the guess marks are lost; answers and grades stay).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-22 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("bloom_ceiling", sa.SmallInteger(), nullable=True))
    op.add_column("courses", sa.Column("bloom_ceiling_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_courses_bloom_ceiling"), "courses", "bloom_ceiling IS NULL OR bloom_ceiling BETWEEN 2 AND 5"
    )
    op.add_column("attempts", sa.Column("guessing", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    op.drop_column("attempts", "guessing")
    op.drop_constraint(op.f("ck_courses_bloom_ceiling"), "courses", type_="check")
    op.drop_column("courses", "bloom_ceiling_confirmed_at")
    op.drop_column("courses", "bloom_ceiling")
