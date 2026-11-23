"""How a note was captured (ADR-011)

Additive: ``notes.captured_via`` says whether the learner typed the note in RecallSpring (``app_ui``), wrote it in a
summary form (``summary_form``) or an assistant transcribed it from the chat or a photo (``assistant_transcription``,
shown with a label so the learner checks it). Existing notes saved by the summary form (their ``note.created``
learning event has origin ``learning_summary``) become ``summary_form``; all others ``app_ui``.

Downgrade drops the column.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-23 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notes", sa.Column("captured_via", sa.String(length=30), nullable=False, server_default=sa.text("'app_ui'"))
    )
    op.create_check_constraint(
        op.f("ck_notes_captured_via"), "notes", "captured_via IN ('app_ui','summary_form','assistant_transcription')"
    )
    op.execute(
        """
        UPDATE notes SET captured_via = 'summary_form'
        WHERE id IN (
            SELECT entity_id FROM learning_events
            WHERE entity_type = 'note' AND event_type = 'note.created' AND payload->>'origin' = 'learning_summary'
        )
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_notes_captured_via"), "notes", type_="check")
    op.drop_column("notes", "captured_via")
