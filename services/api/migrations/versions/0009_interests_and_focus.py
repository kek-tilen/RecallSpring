"""personal interests, focus period and the interest share of the day

Additive only: ``courses.kind`` ('course' for university courses, 'interest' for personal learning without a
deadline), ``courses.focus_until`` (the learner chose to concentrate on this course or interest until that day) and
``users.interest_percent`` (share of each day kept for interests; 0 = university first). Existing rows become
university courses with no focus and no reserved share, so plans stay as they were.

Downgrade note: interests would silently turn into university courses, so the downgrade refuses to run while any
exist.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-21 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("kind", sa.String(length=20), server_default="course", nullable=False))
    op.add_column("courses", sa.Column("focus_until", sa.Date(), nullable=True))
    op.create_check_constraint(op.f("ck_courses_kind"), "courses", "kind IN ('course','interest')")
    op.add_column("users", sa.Column("interest_percent", sa.SmallInteger(), server_default="0", nullable=False))
    op.create_check_constraint(op.f("ck_users_interest_percent"), "users", "interest_percent BETWEEN 0 AND 50")


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM courses WHERE kind = 'interest'"))
    if count:
        raise RuntimeError(f"{count} interests exist; turn them into courses or remove them before downgrading to 0008.")
    op.drop_constraint(op.f("ck_users_interest_percent"), "users", type_="check")
    op.drop_column("users", "interest_percent")
    op.drop_constraint(op.f("ck_courses_kind"), "courses", type_="check")
    op.drop_column("courses", "focus_until")
    op.drop_column("courses", "kind")
