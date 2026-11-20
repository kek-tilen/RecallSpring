"""office documents (docx, pptx, xlsx) as source kinds

Additive only: widens the sources.kind check. Downgrade note: Word/PowerPoint/Excel sources must be removed first
(the old check excludes them), so the downgrade refuses to run while any exist.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-20 18:19:34.752300
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sources_kind"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_kind"), "sources", "kind IN ('pdf','markdown','text','image','docx','pptx','xlsx')"
    )


def downgrade() -> None:
    office = op.get_bind().scalar(sa.text("SELECT count(*) FROM sources WHERE kind IN ('docx','pptx','xlsx')"))
    if office:
        raise RuntimeError(f"{office} Word/PowerPoint/Excel sources exist; remove them before downgrading to 0006.")
    op.drop_constraint(op.f("ck_sources_kind"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_kind"), "sources", "kind IN ('pdf','markdown','text','image')")
