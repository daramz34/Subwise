import uuid

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.schemas import NotificationPreferenceUpdate
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user: CurrentUser, db: DbSession, unread_only: bool = False,
                       limit: int = Query(50, ge=1, le=100)):
    """Also generates any new alerts for you first (safe to call repeatedly)."""
    return notification_service.list_notifications(db, user, unread_only, limit)


@router.get("/preferences")
def get_preferences(user: CurrentUser, db: DbSession):
    prefs = notification_service.get_preferences(db, user)
    db.commit()
    return notification_service.prefs_out(prefs)


@router.patch("/preferences")
def update_preferences(data: NotificationPreferenceUpdate, user: CurrentUser, db: DbSession):
    return notification_service.update_preferences(db, user, data.model_dump(exclude_unset=True))


@router.patch("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return notification_service.mark_read(db, user, notification_id)