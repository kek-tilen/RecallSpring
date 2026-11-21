"""ChatGPT in Chat can use RecallSpring (plan-without-claude.md, Phase 2)

Additive:

- ``ai_conversations.course_id``: the course a conversation studies ("study mode"); null for a general chat.
- ``ai_messages.tool_calls``: on the learner's message, what ChatGPT read or saved in RecallSpring while answering it
  ([{call_id, name, arguments, status, error_code, summary, ms, form?}]). Saved after every step, so the steps stay
  visible when the reply fails. The tools' full outputs are not stored.

Downgrade note: drops both columns; records ChatGPT saved through the tools (questions, grades) stay.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-21 23:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_conversations", sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_ai_conversations_course_id_courses"), "ai_conversations", "courses", ["course_id"], ["id"]
    )
    op.add_column("ai_messages", sa.Column("tool_calls", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_messages", "tool_calls")
    op.drop_constraint(op.f("fk_ai_conversations_course_id_courses"), "ai_conversations", type_="foreignkey")
    op.drop_column("ai_conversations", "course_id")
