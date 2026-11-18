from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.schemas import OverviewOut, PriceChangeOut
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewOut)
def overview(user: CurrentUser, db: DbSession, days: int = Query(30, ge=1, le=365)):
    return analytics_service.get_overview(db, user, days)


@router.get("/price-changes", response_model=list[PriceChangeOut])
def price_changes(user: CurrentUser, db: DbSession):
    return analytics_service.get_price_changes(db, user)