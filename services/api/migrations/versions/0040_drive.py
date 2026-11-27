"""Your Google Drive (2026-11-27)

Additive. ``drive_connections``: one row per learner who connected their own Google Drive (the folder RecallSpring
made, whether new material and exports are copied, from when, and the copy's state). The refresh token is never in
the database (secrets_dir/drive-<user id>.bin). ``drive_items``: what RecallSpring made in that Drive and for which
course, folder, source or export, so nothing is uploaded twice and a renamed course renames its folder.

Downgrade note: drops both tables. Files already in the learners' Drives stay there; the sign-in files in
secrets_dir are then unused and can be deleted.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-27 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drive_connections",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), server_default="google", nullable=False),
        sa.Column("root_id", sa.String(200), nullable=False),
        sa.Column("mirror", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("exports", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("copy_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(20), server_default="ok", nullable=False),
        sa.Column("progress", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_try_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("free_bytes", sa.BigInteger(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("provider IN ('google')", name=op.f("ck_drive_connections_provider")),
        sa.CheckConstraint("state IN ('ok','copying','failing','revoked')", name=op.f("ck_drive_connections_state")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_drive_connections_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_drive_connections")),
    )
    op.create_table(
        "drive_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("local_kind", sa.String(20), nullable=False),
        sa.Column("local_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("drive_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "local_kind IN ('course','source_folder','exports','source','export')",
            name=op.f("ck_drive_items_local_kind"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_drive_items_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_items")),
        sa.UniqueConstraint("user_id", "local_kind", "local_id", name=op.f("uq_drive_items_local")),
    )
    op.create_index(op.f("ix_drive_items_user_id"), "drive_items", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_drive_items_user_id"), table_name="drive_items")
    op.drop_table("drive_items")
    op.drop_table("drive_connections")
