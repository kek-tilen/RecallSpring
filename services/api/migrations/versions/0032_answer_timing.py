"""Answer timing (ADR-014 §3, rollout step 3)

Additive, on ``attempts``: ``answer_seconds``, how long the question was open and visible in a RecallSpring answer
form, without pauses over 5 minutes (1-7200). Chat answers an assistant transcribes have none; nothing is
back-filled, so every existing attempt stays NULL. The planner learns the learner's pace for its review estimates
from it; like focus sessions it records time spent, never learning or mastery.

Downgrade note: drops the column, so the recorded times are lost and the estimates fall back to the defaults.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-26 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("answer_seconds", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_attempts_answer_seconds"),
        "attempts",
        "answer_seconds IS NULL OR answer_seconds BETWEEN 1 AND 7200",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_attempts_answer_seconds"), "attempts", type_="check")
    op.drop_column("attempts", "answer_seconds")
