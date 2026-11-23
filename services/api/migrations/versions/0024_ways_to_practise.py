"""Ways to practise: Concept-to-Clarity explanations, exam answers with a word limit, practice suggestions

Additive (ADR-010, owner decisions 2026-11-23):

* ``explanations`` (one per learner and concept), ``explanation_versions`` (the learner's own explanation, saved
  exactly, numbered v1, v2, ...; soft delete) and ``explanation_feedback`` (an assistant's feedback on one version:
  correct / missing / wrong with cited sections; never a grade).
* ``questions.practice_kind`` (``quiz`` or ``exam_answer``) and the word limit of an exam answer: recommended,
  chosen, who set it and when.
* ``assessments.answer_technique``: separate feedback on how an exam answer used its space (never part of the grade).
* ``users.practice_suggestions``: which kinds of suggestion the learner wants (all on by default).

Downgrade refuses while explanations exist (they are the learner's own text); otherwise it drops all of the above.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-23 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "explanations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("concept_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name=op.f("fk_explanations_concept_id_concepts")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_explanations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_explanations")),
        sa.UniqueConstraint("user_id", "concept_id", name="uq_explanations_user_concept"),
    )
    op.create_index(op.f("ix_explanations_user_id"), "explanations", ["user_id"], unique=False)
    op.create_index(op.f("ix_explanations_concept_id"), "explanations", ["concept_id"], unique=False)
    op.create_table(
        "explanation_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("explanation_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_attempt_id", sa.UUID(), nullable=True),
        sa.Column("word_limit", sa.SmallInteger(), nullable=True),
        sa.Column("client_request_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source IN ('learner','discuss','exam_answer')", name=op.f("ck_explanation_versions_source")
        ),
        sa.CheckConstraint(
            "(source = 'exam_answer') = (source_attempt_id IS NOT NULL)",
            name=op.f("ck_explanation_versions_exam_answer_attempt"),
        ),
        sa.ForeignKeyConstraint(
            ["explanation_id"], ["explanations.id"], name=op.f("fk_explanation_versions_explanation_id_explanations")
        ),
        sa.ForeignKeyConstraint(
            ["source_attempt_id"], ["attempts.id"], name=op.f("fk_explanation_versions_source_attempt_id_attempts")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_explanation_versions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_explanation_versions")),
        sa.UniqueConstraint("explanation_id", "number", name="uq_explanation_versions_number"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_explanation_versions_user_client_request"),
    )
    op.create_index(op.f("ix_explanation_versions_user_id"), "explanation_versions", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_explanation_versions_explanation_id"), "explanation_versions", ["explanation_id"], unique=False
    )
    op.create_table(
        "explanation_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("model_reported_by", sa.String(length=40), nullable=True),
        sa.Column("correct", postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_LIST, nullable=False),
        sa.Column("missing", postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_LIST, nullable=False),
        sa.Column("wrong", postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_LIST, nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), server_default=JSON_LIST, nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["explanation_versions.id"],
            name=op.f("fk_explanation_feedback_version_id_explanation_versions"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_explanation_feedback_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_explanation_feedback")),
    )
    op.create_index(op.f("ix_explanation_feedback_user_id"), "explanation_feedback", ["user_id"], unique=False)
    op.create_index(op.f("ix_explanation_feedback_version_id"), "explanation_feedback", ["version_id"], unique=False)

    op.add_column("questions", sa.Column("practice_kind", sa.String(length=20), server_default="quiz", nullable=False))
    op.add_column("questions", sa.Column("length_recommended_words", sa.SmallInteger(), nullable=True))
    op.add_column("questions", sa.Column("length_words", sa.SmallInteger(), nullable=True))
    op.add_column("questions", sa.Column("length_set_by", sa.String(length=20), nullable=True))
    op.add_column("questions", sa.Column("length_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_questions_practice_kind"), "questions", "practice_kind IN ('quiz','exam_answer')"
    )
    op.create_check_constraint(
        op.f("ck_questions_length_words"),
        "questions",
        "(length_words IS NULL OR length_words BETWEEN 10 AND 1000) AND "
        "(length_recommended_words IS NULL OR length_recommended_words BETWEEN 10 AND 1000)",
    )
    op.create_check_constraint(
        op.f("ck_questions_length_set_by"),
        "questions",
        "length_set_by IS NULL OR length_set_by IN ('assistant','default','learner')",
    )
    op.add_column("assessments", sa.Column("answer_technique", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "practice_suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    n = op.get_bind().scalar(sa.text("SELECT count(*) FROM explanation_versions"))
    if n:
        raise RuntimeError(f"{n} explanation versions exist; downgrading to 0023 would lose the learner's own text.")
    op.drop_column("users", "practice_suggestions")
    op.drop_column("assessments", "answer_technique")
    op.drop_constraint(op.f("ck_questions_length_set_by"), "questions", type_="check")
    op.drop_constraint(op.f("ck_questions_length_words"), "questions", type_="check")
    op.drop_constraint(op.f("ck_questions_practice_kind"), "questions", type_="check")
    for column in ("length_changed_at", "length_set_by", "length_words", "length_recommended_words", "practice_kind"):
        op.drop_column("questions", column)
    op.drop_index(op.f("ix_explanation_feedback_version_id"), table_name="explanation_feedback")
    op.drop_index(op.f("ix_explanation_feedback_user_id"), table_name="explanation_feedback")
    op.drop_table("explanation_feedback")
    op.drop_index(op.f("ix_explanation_versions_explanation_id"), table_name="explanation_versions")
    op.drop_index(op.f("ix_explanation_versions_user_id"), table_name="explanation_versions")
    op.drop_table("explanation_versions")
    op.drop_index(op.f("ix_explanations_concept_id"), table_name="explanations")
    op.drop_index(op.f("ix_explanations_user_id"), table_name="explanations")
    op.drop_table("explanations")
