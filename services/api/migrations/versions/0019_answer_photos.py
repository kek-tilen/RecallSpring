"""photos with answers and chat messages

Additive: ``attempts.photo_ids`` and ``ai_messages.photo_ids`` (JSON lists of source ids, default empty). A learner
can answer with a photo of their work (solved on paper) or paste an image into a Chat message; the photo is saved
first as an image in the course Library (folder "Answer photos" for answers) and the answer or message keeps the
ids. Assistants look at the photos when they grade or reply.

Downgrade note: drops the columns; the photos stay in the Library, only the link to the answer is lost.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-22 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("attempts", "ai_messages"):
        op.add_column(
            table,
            sa.Column("photo_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        )


def downgrade() -> None:
    for table in ("attempts", "ai_messages"):
        op.drop_column(table, "photo_ids")
