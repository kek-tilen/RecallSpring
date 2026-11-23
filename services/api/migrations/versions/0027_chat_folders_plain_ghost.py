"""Chat folders, plain chats and ghost chat usage (ADR-012 §4-5)

Additive:

- ``ai_chat_folders``: the learner's folders for Chat conversations. Top-level folders and one level of subfolders
  (deeper nesting is refused by the server), with a name, an icon from a fixed set, a colour, an optional course
  link and a pin. Deleting a folder is a soft delete; its conversations move to the parent folder or to "No folder".
- ``ai_conversations.folder_id``: the folder a conversation is in (null: "No folder").
- ``ai_conversations.plain``: a plain chat (no course, never RecallSpring's tools).
- ``ai_ghost_usage``: one row per ghost chat reply with the model and token usage only. Ghost chats keep no text,
  title, course or tool arguments anywhere.

Downgrade note: drops the folders (conversations stay, without a folder), the plain flag and the ghost usage rows.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-23 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("icon", sa.String(length=20), server_default="folder", nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name=op.f("ck_ai_chat_folders_not_own_parent")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_ai_chat_folders_course_id_courses")),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["ai_chat_folders.id"], name=op.f("fk_ai_chat_folders_parent_id_ai_chat_folders")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_chat_folders_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_chat_folders")),
    )
    op.create_index(op.f("ix_ai_chat_folders_parent_id"), "ai_chat_folders", ["parent_id"], unique=False)
    op.create_index(op.f("ix_ai_chat_folders_user_id"), "ai_chat_folders", ["user_id"], unique=False)
    op.add_column("ai_conversations", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_ai_conversations_folder_id"), "ai_conversations", ["folder_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_ai_conversations_folder_id_ai_chat_folders"),
        "ai_conversations",
        "ai_chat_folders",
        ["folder_id"],
        ["id"],
    )
    op.add_column(
        "ai_conversations", sa.Column("plain", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.create_table(
        "ai_ghost_usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outcome", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_ghost_usage_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_ghost_usage")),
    )
    op.create_index(op.f("ix_ai_ghost_usage_user_id"), "ai_ghost_usage", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_ghost_usage_user_id"), table_name="ai_ghost_usage")
    op.drop_table("ai_ghost_usage")
    op.drop_column("ai_conversations", "plain")
    op.drop_constraint(
        op.f("fk_ai_conversations_folder_id_ai_chat_folders"), "ai_conversations", type_="foreignkey"
    )
    op.drop_index(op.f("ix_ai_conversations_folder_id"), table_name="ai_conversations")
    op.drop_column("ai_conversations", "folder_id")
    op.drop_index(op.f("ix_ai_chat_folders_user_id"), table_name="ai_chat_folders")
    op.drop_index(op.f("ix_ai_chat_folders_parent_id"), table_name="ai_chat_folders")
    op.drop_table("ai_chat_folders")
