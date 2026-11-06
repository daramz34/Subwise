import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.core.deps import CurrentUser, DbSession, UserPlan
from app.schemas import (
    DetailOut, DuplicateWarningOut, PaymentCreate, PaymentOut, PriceHistoryOut,
    SubscriptionBulkIn, SubscriptionCreate, SubscriptionFilters, SubscriptionOut,
    SubscriptionPage, SubscriptionStatusIn, SubscriptionUpdate,
)
from app.services import subscription_service as svc

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED,
             responses={409: {"model": DuplicateWarningOut}})
def create_subscription(body: SubscriptionCreate, user: CurrentUser, plan: UserPlan, db: DbSession):
    try:
        return svc.create_subscription(db, user, plan, body)
    except svc.DuplicateSubscriptionError as exc:
        warning = DuplicateWarningOut(
            detail="You already have a similar subscription. Send acknowledge_duplicate=true to add it anyway.",
            similar_subscription_ids=exc.similar_ids,
        )
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=warning.model_dump(mode="json"))


@router.get("", response_model=SubscriptionPage)
def list_subscriptions(filters: Annotated[SubscriptionFilters, Query()], user: CurrentUser, db: DbSession):
    items, total = svc.list_subscriptions(db, user, filters)
    return {"items": items, "total": total, "page": filters.page, "page_size": filters.page_size}


@router.post("/bulk", response_model=DetailOut)
def bulk_action(body: SubscriptionBulkIn, user: CurrentUser, db: DbSession):
    updated, skipped = svc.bulk_apply(db, user, body)
    return DetailOut(detail=f"{updated} subscription(s) updated, {skipped} skipped.")


@router.get("/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(subscription_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return svc.get_subscription(db, user, subscription_id)


@router.put("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(subscription_id: uuid.UUID, body: SubscriptionUpdate, user: CurrentUser, db: DbSession):
    """Partial update: only the fields you send are changed."""
    return svc.update_subscription(db, user, subscription_id, body)


@router.patch("/{subscription_id}/status", response_model=SubscriptionOut)
def change_status(subscription_id: uuid.UUID, body: SubscriptionStatusIn, user: CurrentUser, db: DbSession):
    return svc.set_status(db, user, subscription_id, body.status)


@router.delete("/{subscription_id}", response_model=DetailOut)
def archive_subscription(subscription_id: uuid.UUID, user: CurrentUser, db: DbSession):
    svc.archive_subscription(db, user, subscription_id)
    return DetailOut(detail="Subscription archived")


@router.get("/{subscription_id}/price-history", response_model=list[PriceHistoryOut])
def price_history(subscription_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return svc.list_price_history(db, user, subscription_id)


@router.post("/{subscription_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(subscription_id: uuid.UUID, body: PaymentCreate, user: CurrentUser, db: DbSession):
    return svc.create_payment(db, user, subscription_id, body)


@router.get("/{subscription_id}/payments", response_model=list[PaymentOut])
def payments(subscription_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return svc.list_payments(db, user, subscription_id)