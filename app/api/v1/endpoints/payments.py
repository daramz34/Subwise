from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.deps import CurrentUser, DbSession
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])        # /payments
plans_router = APIRouter(prefix="/plans", tags=["plans"])  # /plans


class CreateOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")   # an "amount" sent by the client is rejected
    plan_code: str = Field(min_length=1, max_length=20)


class CaptureOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=5, max_length=64)


@plans_router.get("")
def plans(db: DbSession):
    return [{"code": p.code, "name": p.name, "price": f"{p.price:.2f}", "currency": p.currency,
             "duration_days": p.duration_days, "limits": p.limits}
            for p in payment_service.list_plans(db)]


@router.post("/create-order", status_code=201)
def create_order(data: CreateOrderIn, user: CurrentUser, db: DbSession):
    return payment_service.create_order(db, user, data.plan_code)


@router.post("/capture-order")
def capture_order(data: CaptureOrderIn, user: CurrentUser, db: DbSession):
    return payment_service.capture_order(db, user, data.order_id)


@router.get("/orders")
def orders(user: CurrentUser, db: DbSession):
    return payment_service.list_orders(db, user)


@router.get("/entitlement")
def entitlement(user: CurrentUser, db: DbSession):
    return payment_service.entitlement_info(db, user)


@router.post("/webhook")
async def webhook(request: Request, db: DbSession):
    raw = await request.body()   # the raw body, as PayPal sent it
    return payment_service.handle_webhook(db, request.headers, raw)