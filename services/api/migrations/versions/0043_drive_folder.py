"""Your cloud folder in a synced folder (2026-11-28)

``drive_connections.provider`` may now be ``folder`` (a synced folder such as iCloud Drive, cloud_folder.py) as well
as ``google``, ``dropbox`` and ``onedrive``. A synced folder refers to what it made by its path inside the folder,
which can be longer than a cloud file id, so ``drive_connections.root_id`` and ``drive_items.drive_id`` become text.
No data is changed. Cloud copy keeps its provider in the backup settings file, not the database.

Downgrade note: refused while any learner uses a synced folder (disconnect it first in Settings › Data & backups ›
Your cloud folder), so no row is lost; then the constraint allows only the three cloud providers again and the two
columns go back to 200 characters (cloud ids are shorter).

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-28 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_drive_connections_provider"), "drive_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_drive_connections_provider"),
        "drive_connections",
        "provider IN ('google','dropbox','onedrive','folder')",
    )
    op.alter_column("drive_connections", "root_id", type_=sa.Text(), existing_type=sa.String(200), nullable=False)
    op.alter_column("drive_items", "drive_id", type_=sa.Text(), existing_type=sa.String(200), nullable=False)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM drive_connections WHERE provider = 'folder'")).scalar()
    if n:
        raise RuntimeError(f"{n} learner(s) use a synced folder as their cloud folder; disconnect it first")
    op.alter_column("drive_items", "drive_id", type_=sa.String(200), existing_type=sa.Text(), nullable=False)
    op.alter_column("drive_connections", "root_id", type_=sa.String(200), existing_type=sa.Text(), nullable=False)
    op.drop_constraint(op.f("ck_drive_connections_provider"), "drive_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_drive_connections_provider"), "drive_connections", "provider IN ('google','dropbox','onedrive')"
    )
