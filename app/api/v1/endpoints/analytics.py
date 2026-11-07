from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(user: CurrentUser, db: DbSession, days: int = Query(30, ge=1, le=365)):
    return analytics_service.get_overview(db, user, days)


@router.get("/price-changes")
def price_changes(user: CurrentUser, db: DbSession):
    return analytics_service.get_price_changes(db, user)