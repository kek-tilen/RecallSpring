"""What Home calls the learner (ADR-012)

Additive: ``users.greeting_name`` (at most 40 characters, nullable). Home greets "Good evening, <name>" when it is
set and "Good evening" when it is not (the default). Set in Settings → Profile.

Downgrade drops the column.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-23 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("greeting_name", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "greeting_name")
