"""Your cloud folder in OneDrive (2026-11-28)

``drive_connections.provider`` may now be ``onedrive`` as well as ``google`` and ``dropbox``: only the check
constraint changes. No data is changed. Cloud copy keeps its provider in secrets_dir, not the database.

Downgrade note: refused while any learner has OneDrive connected (disconnect it first in Settings › Data & backups ›
Your cloud folder), so no row is lost; then the constraint allows only ``google`` and ``dropbox`` again.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-28 03:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_drive_connections_provider"), "drive_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_drive_connections_provider"), "drive_connections", "provider IN ('google','dropbox','onedrive')"
    )


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM drive_connections WHERE provider = 'onedrive'")).scalar()
    if n:
        raise RuntimeError(f"{n} learner(s) have OneDrive connected as their cloud folder; disconnect it first")
    op.drop_constraint(op.f("ck_drive_connections_provider"), "drive_connections", type_="check")
    op.create_check_constraint(
        op.f("ck_drive_connections_provider"), "drive_connections", "provider IN ('google','dropbox')"
    )
