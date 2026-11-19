"""Append-only learning events and audit records. Payloads never contain raw answers, notes or source text."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from .. import clock
from ..models import AuditEvent, LearningEvent


def learning_event(
    db: Session,
    *,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    request_id: str | None,
) -> None:
    db.add(
        LearningEvent(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            correlation_id=request_id,
            occurred_at=clock.now(),
        )
    )


def audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            request_id=request_id,
            occurred_at=clock.now(),
        )
    )
