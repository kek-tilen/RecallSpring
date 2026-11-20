"""more source formats: OpenDocument, CSV, subtitles, notebooks, code, LaTeX

Additive only: widens the sources.kind check. Downgrade note: sources of the new kinds must be removed first (the
old check excludes them), so the downgrade refuses to run while any exist.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-20 21:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "'pdf','markdown','text','image','docx','pptx','xlsx'"
NEW = "'odt','odp','ods','csv','subtitles','notebook','code','latex'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sources_kind"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_kind"), "sources", f"kind IN ({OLD},{NEW})")


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text(f"SELECT count(*) FROM sources WHERE kind IN ({NEW})"))
    if count:
        raise RuntimeError(f"{count} sources of the newer formats exist; remove them before downgrading to 0007.")
    op.drop_constraint(op.f("ck_sources_kind"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_kind"), "sources", f"kind IN ({OLD})")
