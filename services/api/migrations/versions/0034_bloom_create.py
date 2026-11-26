"""Bloom 6 Create as a practice limit (2026-11-26)

``courses.bloom_ceiling`` may now be 2-6 (it was 2-5). NULL keeps meaning "automatic", which is 5 Evaluate, or 6
Create while an upcoming exam's profile has Bloom 6 questions; an explicit 5 is now stored as 5. No data changes on
upgrade: every existing NULL stays automatic.

Downgrade note: a limit of 5 or 6 becomes NULL again (the old "no limit", which meant 5), then the 2-5 check is
restored; limits 2-4 are kept.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-26 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_courses_bloom_ceiling"), "courses", type_="check")
    op.create_check_constraint(
        op.f("ck_courses_bloom_ceiling"), "courses", "bloom_ceiling IS NULL OR bloom_ceiling BETWEEN 2 AND 6"
    )


def downgrade() -> None:
    op.execute("UPDATE courses SET bloom_ceiling = NULL WHERE bloom_ceiling >= 5")
    op.drop_constraint(op.f("ck_courses_bloom_ceiling"), "courses", type_="check")
    op.create_check_constraint(
        op.f("ck_courses_bloom_ceiling"), "courses", "bloom_ceiling IS NULL OR bloom_ceiling BETWEEN 2 AND 5"
    )
