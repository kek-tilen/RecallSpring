"""library folders and archived material

Additive only: ``source_folders`` (the learner's own folders inside a course, nestable), ``sources.folder_id``
(null = the course's top level) and ``sources.archived_at`` (archived material is hidden from the library and from
search but kept, still citable and restorable). Existing material stays at the top level of its course, not
archived, so nothing changes until the learner files something.

Downgrade note: folders and archive marks would be lost, so the downgrade refuses to run while any folder exists or
any material is archived.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-21 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name=op.f("ck_source_folders_not_own_parent")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name=op.f("fk_source_folders_course_id_courses")),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["source_folders.id"], name=op.f("fk_source_folders_parent_id_source_folders")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_source_folders_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_folders")),
    )
    op.create_index(op.f("ix_source_folders_course_id"), "source_folders", ["course_id"], unique=False)
    op.create_index(op.f("ix_source_folders_parent_id"), "source_folders", ["parent_id"], unique=False)
    op.create_index(op.f("ix_source_folders_user_id"), "source_folders", ["user_id"], unique=False)
    op.add_column("sources", sa.Column("folder_id", sa.UUID(), nullable=True))
    op.add_column("sources", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_sources_folder_id"), "sources", ["folder_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_sources_folder_id_source_folders"), "sources", "source_folders", ["folder_id"], ["id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    folders = bind.scalar(sa.text("SELECT count(*) FROM source_folders"))
    archived = bind.scalar(sa.text("SELECT count(*) FROM sources WHERE archived_at IS NOT NULL"))
    if folders or archived:
        raise RuntimeError(
            f"{folders} folders and {archived} archived files exist; move material out of folders and restore it "
            "before downgrading to 0009."
        )
    op.drop_constraint(op.f("fk_sources_folder_id_source_folders"), "sources", type_="foreignkey")
    op.drop_index(op.f("ix_sources_folder_id"), table_name="sources")
    op.drop_column("sources", "archived_at")
    op.drop_column("sources", "folder_id")
    op.drop_index(op.f("ix_source_folders_user_id"), table_name="source_folders")
    op.drop_index(op.f("ix_source_folders_parent_id"), table_name="source_folders")
    op.drop_index(op.f("ix_source_folders_course_id"), table_name="source_folders")
    op.drop_table("source_folders")
