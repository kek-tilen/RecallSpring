"""saved conversations with ChatGPT

Additive: ``ai_conversations`` and ``ai_messages`` keep what the learner asked ChatGPT from Settings and each
reply's details (model and version that answered, time, duration, token usage). The learner's message is saved
before the request; conversations stay after signing out of ChatGPT. Existing rows are unchanged.

Downgrade note: refuses while any conversation exists, since it would be lost.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-21 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('chatgpt')", name=op.f("ck_ai_conversations_provider")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_conversations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
    )
    op.create_index(op.f("ix_ai_conversations_user_id"), "ai_conversations", ["user_id"], unique=False)
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("client_request_id", sa.UUID(), nullable=True),
        sa.Column("model_requested", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("response_id", sa.String(length=200), nullable=True),
        sa.Column("account", sa.String(length=320), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user','assistant')", name=op.f("ck_ai_messages_role")),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], name=op.f("fk_ai_messages_conversation_id_ai_conversations")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_messages_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
        sa.UniqueConstraint("conversation_id", "position", name="uq_ai_messages_position"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_ai_messages_user_client_request"),
    )
    op.create_index(op.f("ix_ai_messages_conversation_id"), "ai_messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_ai_messages_user_id"), "ai_messages", ["user_id"], unique=False)


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM ai_conversations"))
    if count:
        raise RuntimeError(f"{count} ChatGPT conversations exist; they would be lost by downgrading to 0011.")
    op.drop_index(op.f("ix_ai_messages_user_id"), table_name="ai_messages")
    op.drop_index(op.f("ix_ai_messages_conversation_id"), table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index(op.f("ix_ai_conversations_user_id"), table_name="ai_conversations")
    op.drop_table("ai_conversations")
