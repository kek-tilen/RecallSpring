"""Exam profile v2 (ADR-013 §1)

Additive, on ``target_profiles``:

- ``version``: 1 for existing analyses (topic weights only), 2 for the new shape.
- ``topics``: each topic with points or share, the course concepts that cover it (or ``not_in_material``), where it
  is on the paper, the papers it appeared on, and the share and weight RecallSpring computed.
- ``papers``: the old papers the analysis read (source, label such as the year, total points, duration).
- ``unreadable``: what the assistant could not make out on the papers.
- ``confirmed_at`` / ``confirmed_via``: the learner confirmed the analysis (through the assistant or the web app).

Existing rows stay version 1 and unconfirmed; nothing is rewritten.

Downgrade note: drops the new columns, so v2 analyses lose their topics, papers and confirmation (their item types,
Bloom mix, examples and notes stay).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-25 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column("target_profiles", sa.Column("version", sa.SmallInteger(), server_default="1", nullable=False))
    op.add_column("target_profiles", sa.Column("topics", postgresql.JSONB(), server_default=JSON_LIST, nullable=False))
    op.add_column("target_profiles", sa.Column("papers", postgresql.JSONB(), server_default=JSON_LIST, nullable=False))
    op.add_column(
        "target_profiles", sa.Column("unreadable", postgresql.JSONB(), server_default=JSON_LIST, nullable=False)
    )
    op.add_column("target_profiles", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("target_profiles", sa.Column("confirmed_via", sa.String(length=20), nullable=True))
    op.create_check_constraint(op.f("ck_target_profiles_version"), "target_profiles", "version IN (1, 2)")
    op.create_check_constraint(
        op.f("ck_target_profiles_confirmed_via"),
        "target_profiles",
        "confirmed_via IS NULL OR confirmed_via IN ('assistant','web')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_target_profiles_confirmed_via"), "target_profiles", type_="check")
    op.drop_constraint(op.f("ck_target_profiles_version"), "target_profiles", type_="check")
    for column in ("confirmed_via", "confirmed_at", "unreadable", "papers", "topics", "version"):
        op.drop_column("target_profiles", column)
