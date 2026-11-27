"""Passkeys and password changes (2026-11-27)

Additive. ``passkeys``: one row per WebAuthn credential (credential id, the public key, the signature counter,
transports, whether a password manager syncs it, the authenticator's AAGUID, a name, the address it works at
(``rp_id``), added and last used). No secret is stored: the private key never leaves the learner's device.
``users.password_changed_at``: set by Change password and ``recallspring reset-password``.
``auth_sessions.confirmed_at``: "Confirm it is you" before adding or removing a passkey (valid 5 minutes).

Downgrade note: drops the table and both columns, so every passkey stops working (the password still does) and
Settings no longer knows when the password was last changed.

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-27 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("auth_sessions", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "passkeys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("transports", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("backed_up", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("aaguid", sa.String(36), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("rp_id", sa.String(253), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_passkeys_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passkeys")),
        sa.UniqueConstraint("credential_id", name=op.f("uq_passkeys_credential_id")),
    )
    op.create_index(op.f("ix_passkeys_user_id"), "passkeys", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_passkeys_user_id"), table_name="passkeys")
    op.drop_table("passkeys")
    op.drop_column("auth_sessions", "confirmed_at")
    op.drop_column("users", "password_changed_at")
