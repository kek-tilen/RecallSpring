"""imported chats and study preferences

Additive: material can be an imported chat (``sources.category`` 'chat', ``sources.origin`` 'import'), e.g.
conversations from a ChatGPT data export saved word for word; ``users.study_preferences`` keeps the learner's own
words on how they like to study (for example their ChatGPT custom instructions), which Claude reads. Existing rows
are unchanged.

Downgrade note: refuses while imported chats exist or preferences are set, since they would no longer fit.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-21 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sources_category"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_category"),
        "sources",
        "category IN ('material','notes','exercises','past_paper','chat','other')",
    )
    op.drop_constraint(op.f("ck_sources_origin"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_origin"), "sources", "origin IN ('upload','paste','import')")
    op.add_column("users", sa.Column("study_preferences", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    chats = bind.scalar(sa.text("SELECT count(*) FROM sources WHERE category = 'chat' OR origin = 'import'"))
    prefs = bind.scalar(sa.text("SELECT count(*) FROM users WHERE study_preferences IS NOT NULL"))
    if chats or prefs:
        raise RuntimeError(
            f"{chats} imported chats and {prefs} study preferences exist; remove them before downgrading to 0010."
        )
    op.drop_column("users", "study_preferences")
    op.drop_constraint(op.f("ck_sources_origin"), "sources", type_="check")
    op.create_check_constraint(op.f("ck_sources_origin"), "sources", "origin IN ('upload','paste')")
    op.drop_constraint(op.f("ck_sources_category"), "sources", type_="check")
    op.create_check_constraint(
        op.f("ck_sources_category"), "sources", "category IN ('material','notes','exercises','past_paper','other')"
    )
