"""Exports (2026-11-27)

Additive. ``exports``: one row per export a learner asked for (their own material by course, notes as Markdown,
answers and grades as CSV and JSON), with its state, options, progress, counts, size and when the finished ZIP
expires (24 hours). The ZIP itself lives under storage_dir/exports/<user id>/, never in the database.

Downgrade note: drops the table; finished ZIPs still on disk are no longer listed and can be deleted by hand.

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-27 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(20), server_default="queued", nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("destination", sa.String(20), server_default="download", nullable=False),
        sa.Column("progress", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("counts", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued','running','ready','failed','cancelled','expired')", name=op.f("ck_exports_state")
        ),
        sa.CheckConstraint("destination IN ('download','drive')", name=op.f("ck_exports_destination")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_exports_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exports")),
    )
    op.create_index(op.f("ix_exports_user_id"), "exports", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_exports_user_id"), table_name="exports")
    op.drop_table("exports")
