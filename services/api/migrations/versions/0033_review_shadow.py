"""FSRS-6 in shadow (ADR-014 §5, rollout step 4)

Additive: ``review_shadow``, a derived table rebuilt by every replay of a concept's review state and never edited.
One row per variant (``rs-fsrs6-v1``: Partial as Hard; ``rs-fsrs6-v1a``: Partial as Again) and review: the
attempt, the local date, the grade, the rating and the Bloom level, the evaluator kind and confidence, the elapsed
days, R, S and D before the review and S and D after it, FSRS's date and the capped date, R on the morning of the
concept's next exam, the library version and a hash of the parameters. Nothing in the web app or the connector reads
it; ``recallspring shadow-report`` does. It starts empty; ``recallspring recompute-reviews`` fills it from the
existing evidence.

Downgrade note: drops the table. Nothing is lost that a replay cannot rebuild.

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-26 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_shadow",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("concept_id", sa.UUID(), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("bloom_level", sa.SmallInteger(), nullable=True),
        sa.Column("evaluator_kind", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("elapsed_days", sa.Integer(), nullable=True),
        sa.Column("r_before", sa.Float(), nullable=True),
        sa.Column("s_before", sa.Float(), nullable=True),
        sa.Column("d_before", sa.Float(), nullable=True),
        sa.Column("s_after", sa.Float(), nullable=False),
        sa.Column("d_after", sa.Float(), nullable=False),
        sa.Column("fsrs_due", sa.Date(), nullable=False),
        sa.Column("capped_due", sa.Date(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("exam_target", sa.Float(), nullable=True),
        sa.Column("exam_r", sa.Float(), nullable=True),
        sa.Column("library_version", sa.String(length=20), nullable=False),
        sa.Column("params_hash", sa.String(length=16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("variant IN ('rs-fsrs6-v1','rs-fsrs6-v1a')", name=op.f("ck_review_shadow_variant")),
        sa.CheckConstraint("source IN ('answer','check_first')", name=op.f("ck_review_shadow_source")),
        sa.CheckConstraint("rating BETWEEN 1 AND 4", name=op.f("ck_review_shadow_rating")),
        sa.CheckConstraint("grade IS NULL OR grade BETWEEN 0 AND 4", name=op.f("ck_review_shadow_grade")),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], name=op.f("fk_review_shadow_attempt_id_attempts")),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name=op.f("fk_review_shadow_concept_id_concepts")),
        sa.ForeignKeyConstraint(
            ["target_id"], ["study_targets.id"], name=op.f("fk_review_shadow_target_id_study_targets")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_review_shadow_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_shadow")),
    )
    op.create_index(op.f("ix_review_shadow_attempt_id"), "review_shadow", ["attempt_id"], unique=False)
    op.create_index(op.f("ix_review_shadow_concept_id"), "review_shadow", ["concept_id"], unique=False)
    op.create_index(
        "ix_review_shadow_review", "review_shadow", ["user_id", "concept_id", "variant", "local_date"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_review_shadow_review", table_name="review_shadow")
    op.drop_index(op.f("ix_review_shadow_concept_id"), table_name="review_shadow")
    op.drop_index(op.f("ix_review_shadow_attempt_id"), table_name="review_shadow")
    op.drop_table("review_shadow")
