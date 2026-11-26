"""Before this exam: the learner's choice per study target (ADR-014 §4, rollout step 2)

Additive, on ``study_targets``: ``exam_retention``, the target for the exam morning the learner chose for the days
before the exam ("Regular reviews only" 0.90, "An extra review before the exam" 0.95, "Intense" 0.97). NULL means
the default of the target's goal (0.95 exam only, 0.90 long term), so every existing row keeps today's schedule;
nothing is rewritten. The check allows 0.85-0.97 (phase B may add a lighter choice).

Downgrade note: drops the column, so the learners' choices are lost and every target falls back to its goal's
default (review dates follow at the next recompute).

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-26 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("study_targets", sa.Column("exam_retention", sa.Numeric(3, 2), nullable=True))
    op.create_check_constraint(
        op.f("ck_study_targets_exam_retention"),
        "study_targets",
        "exam_retention IS NULL OR exam_retention BETWEEN 0.85 AND 0.97",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_study_targets_exam_retention"), "study_targets", type_="check")
    op.drop_column("study_targets", "exam_retention")
