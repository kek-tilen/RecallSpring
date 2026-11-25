"""Web sources (ADR-013 §5)

Additive:

- ``sources.origin`` may be ``web``: content an assistant read on the web, added only after the learner agreed,
  for something on an old paper that the course material does not cover. Its file name starts with "From the web".
- ``sources.web_links``: the pages it came from (URL, title, the day it was read).

Downgrade note: refuses while web sources exist, since they would no longer fit; then drops the column.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-25 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("web_links", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.drop_constraint(op.f("ck_sources_origin"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_origin"), "sources", "origin IN ('upload','paste','import','web')")


def downgrade() -> None:
    web = op.get_bind().scalar(sa.text("SELECT count(*) FROM sources WHERE origin = 'web'"))
    if web:
        raise RuntimeError(f"{web} web sources exist; remove them before downgrading to 0028.")
    op.drop_constraint(op.f("ck_sources_origin"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_origin"), "sources", "origin IN ('upload','paste','import')")
    op.drop_column("sources", "web_links")
