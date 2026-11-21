"""material the learner lets a ChatGPT conversation use

Additive: ``ai_conversation_sources`` holds the files the learner chose for a conversation, and
``ai_messages.context`` records which excerpts of them were sent with each message (section IDs, file, citation
label), so every reply stays traceable to its evidence. Existing rows are unchanged.

Downgrade note: refuses while any conversation has chosen material or a message records sent excerpts, since that
record would be lost.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21 18:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversation_sources",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_conversation_sources_conversation_id_ai_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_ai_conversation_sources_source_id_sources")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_conversation_sources_user_id_users")),
        sa.PrimaryKeyConstraint("conversation_id", "source_id", name=op.f("pk_ai_conversation_sources")),
    )
    op.create_index(op.f("ix_ai_conversation_sources_user_id"), "ai_conversation_sources", ["user_id"], unique=False)
    op.add_column("ai_messages", sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    chosen = bind.scalar(sa.text("SELECT count(*) FROM ai_conversation_sources"))
    sent = bind.scalar(sa.text("SELECT count(*) FROM ai_messages WHERE context IS NOT NULL"))
    if chosen or sent:
        raise RuntimeError(
            f"{chosen} chosen files and {sent} messages with sent excerpts exist; downgrading to 0012 would lose them."
        )
    op.drop_column("ai_messages", "context")
    op.drop_index(op.f("ix_ai_conversation_sources_user_id"), table_name="ai_conversation_sources")
    op.drop_table("ai_conversation_sources")
