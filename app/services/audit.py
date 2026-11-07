"""Audit trail. log_event() adds a row but does NOT commit: the caller's commit saves the
audit row and the change it describes together, so one can never exist without the other."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import AuditLog


def to_jsonable(value):
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def log_event(db: Session, user_id, entity_type: str, entity_id, action: str,
              old: dict | None = None, new: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_values=to_jsonable(old) if old is not None else None,
        new_values=to_jsonable(new) if new is not None else None,
    ))