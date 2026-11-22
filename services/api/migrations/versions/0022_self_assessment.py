"""Self-assessment as an evaluator kind

Additive: ``assessments.evaluator_kind`` may be ``self``, a grade the learner gave their own answer by checking it
against the question's expected points. It is always provisional and waits for an assistant to check it
(owner decision 2026-11-22).

Downgrade note: refuses while any self-assessment exists (it would otherwise look like a correction or an AI grade).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-22 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_assessments_evaluator_kind"), "assessments", type_="check")
    op.create_check_constraint(
        op.f("ck_assessments_evaluator_kind"), "assessments", "evaluator_kind IN ('ai','human','deterministic','self')"
    )


def downgrade() -> None:
    n = op.get_bind().scalar(sa.text("SELECT count(*) FROM assessments WHERE evaluator_kind = 'self'"))
    if n:
        raise RuntimeError(f"{n} self-assessments exist; they cannot be represented before revision 0022.")
    op.drop_constraint(op.f("ck_assessments_evaluator_kind"), "assessments", type_="check")
    op.create_check_constraint(
        op.f("ck_assessments_evaluator_kind"), "assessments", "evaluator_kind IN ('ai','human','deterministic')"
    )
