"""removing a wrongly timed focus block

Additive: ``focus_sessions.deleted_at``. A block the learner removes (after confirming) is soft deleted, no longer
counts as focus time, and can be restored for 30 days; both are audited. Existing rows stay as they are (NULL).

Downgrade note: refuses while any block is removed, since dropping the column would silently count it again.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-21 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("focus_sessions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    n = op.get_bind().scalar(sa.text("SELECT count(*) FROM focus_sessions WHERE deleted_at IS NOT NULL"))
    if n:
        raise RuntimeError(f"{n} focus blocks are removed; downgrading to 0014 would count them again.")
    op.drop_column("focus_sessions", "deleted_at")
