"""Simulation retakes (2026-11-26)

Additive, on ``quizzes``:

- ``retake_of``: the first version of the simulation (the benchmark) for every retake; NULL for a first version.
- ``version``: 1 for a first version, 2, 3, ... for its retakes (a retake reuses the same questions).
- ``same_day_practice``: set when a retake is submitted on the same day (the learner's time zone) as an earlier
  version; its answers are graded and shown, but stay out of the review schedule and the Bloom ramp, like a
  diagnostic check.

Every existing simulation is a first version (version 1, not a retake, not same-day practice); nothing is rewritten.

Downgrade note: retakes become ordinary simulations (the link to their first version and their version number are
lost) and same-day retake answers count in the review schedule again at the next recompute.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-26 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("quizzes", sa.Column("retake_of", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(op.f("fk_quizzes_retake_of_quizzes"), "quizzes", "quizzes", ["retake_of"], ["id"])
    op.create_index(op.f("ix_quizzes_retake_of"), "quizzes", ["retake_of"])
    op.add_column("quizzes", sa.Column("version", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column(
        "quizzes", sa.Column("same_day_practice", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.create_check_constraint(
        op.f("ck_quizzes_retake_version"),
        "quizzes",
        "(retake_of IS NULL AND version = 1) OR (retake_of IS NOT NULL AND version >= 2)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_quizzes_retake_version"), "quizzes", type_="check")
    op.drop_column("quizzes", "same_day_practice")
    op.drop_column("quizzes", "version")
    op.drop_index(op.f("ix_quizzes_retake_of"), table_name="quizzes")
    op.drop_constraint(op.f("fk_quizzes_retake_of_quizzes"), "quizzes", type_="foreignkey")
    op.drop_column("quizzes", "retake_of")
