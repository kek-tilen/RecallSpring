"""Past papers left out of an exam analysis (owner 2026-11-25)

Additive, on ``target_profiles``: ``skipped_papers``, the past papers of the course an analysis leaves out on the
learner's word (source and reason). With it RecallSpring can tell which past papers an analysis has not looked at.
Existing rows get an empty list; nothing is rewritten.

Downgrade note: drops the column, so the reasons are lost (those papers then show as not looked at).

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-25 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "target_profiles",
        sa.Column("skipped_papers", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("target_profiles", "skipped_papers")
