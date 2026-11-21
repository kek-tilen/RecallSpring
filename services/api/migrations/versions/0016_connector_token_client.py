"""which assistant a connector token belongs to

Additive: ``connector_tokens.client`` (``claude`` or ``codex``), so RecallSpring knows which assistant made a request
and labels its grades ("Claude", "Codex"). Existing tokens were all made for Claude Desktop and become ``claude``.

Downgrade note: refuses while any Codex token exists, since dropping the column would make its grades look like
Claude's.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-21 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connector_tokens",
        sa.Column("client", sa.String(20), nullable=False, server_default="claude"),
    )
    op.create_check_constraint(op.f("ck_connector_tokens_client"), "connector_tokens", "client IN ('claude','codex')")


def downgrade() -> None:
    n = op.get_bind().scalar(sa.text("SELECT count(*) FROM connector_tokens WHERE client <> 'claude'"))
    if n:
        raise RuntimeError(f"{n} connector tokens belong to Codex; downgrading to 0015 would label them as Claude.")
    op.drop_constraint(op.f("ck_connector_tokens_client"), "connector_tokens", type_="check")
    op.drop_column("connector_tokens", "client")
