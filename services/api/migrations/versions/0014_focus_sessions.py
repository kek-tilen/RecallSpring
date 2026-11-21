"""Pomodoro focus time

Additive: ``focus_sessions`` records each focus block the learner timed in the web app (optionally for one course):
when it ran, the planned length, the time actually focused (pauses excluded) and whether it ran to the end. It is
time spent, not evidence of learning. Existing tables are unchanged.

Downgrade note: refuses while any focus session exists, since that record would be lost.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "focus_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=True),
        sa.Column("client_session_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("focused_seconds", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("planned_minutes BETWEEN 1 AND 240", name=op.f("ck_focus_sessions_planned_minutes")),
        sa.CheckConstraint("focused_seconds BETWEEN 60 AND 14400", name=op.f("ck_focus_sessions_focused_seconds")),
        sa.CheckConstraint("ended_at >= started_at", name=op.f("ck_focus_sessions_ended_after_start")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_focus_sessions_course_id_courses")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_focus_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_focus_sessions")),
        sa.UniqueConstraint("user_id", "client_session_id", name="uq_focus_sessions_user_client_session"),
    )
    op.create_index(op.f("ix_focus_sessions_user_id"), "focus_sessions", ["user_id"], unique=False)
    op.create_index("ix_focus_sessions_user_ended", "focus_sessions", ["user_id", "ended_at"], unique=False)


def downgrade() -> None:
    n = op.get_bind().scalar(sa.text("SELECT count(*) FROM focus_sessions"))
    if n:
        raise RuntimeError(f"{n} focus sessions exist; downgrading to 0013 would lose them.")
    op.drop_index("ix_focus_sessions_user_ended", table_name="focus_sessions")
    op.drop_index(op.f("ix_focus_sessions_user_id"), table_name="focus_sessions")
    op.drop_table("focus_sessions")
