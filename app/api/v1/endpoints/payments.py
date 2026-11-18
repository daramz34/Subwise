from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbSession
from app.schemas import (
    CaptureOrderIn, CaptureOrderOut, CreateOrderIn, CreateOrderOut,
    DetailOut, EntitlementOut, OrderOut, PlanOut,
)
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])  # /payments
plans_router = APIRouter(prefix="/plans", tags=["plans"])  # /plans


@plans_router.get("", response_model=list[PlanOut])
def plans(db: DbSession):
    return [{"code": p.code, "name": p.name, "price": f"{p.price:.2f}", "currency": p.currency,
             "duration_days": p.duration_days, "limits": p.limits}
            for p in payment_service.list_plans(db)]


@router.post("/create-order", status_code=201, response_model=CreateOrderOut)
def create_order(data: CreateOrderIn, user: CurrentUser, db: DbSession):
    return payment_service.create_order(db, user, data.plan_code)


@router.post("/capture-order", response_model=CaptureOrderOut)
def capture_order(data: CaptureOrderIn, user: CurrentUser, db: DbSession):
    return payment_service.capture_order(db, user, data.order_id)


@router.get("/orders", response_model=list[OrderOut])
def orders(user: CurrentUser, db: DbSession):
    return payment_service.list_orders(db, user)


@router.get("/entitlement", response_model=EntitlementOut)
def entitlement(user: CurrentUser, db: DbSession):
    return payment_service.entitlement_info(db, user)


@router.post("/webhook", response_model=DetailOut)
async def webhook(request: Request, db: DbSession):
    raw = await request.body()   # the raw body, as PayPal sent it
    return payment_service.handle_webhook(db, request.headers, raw)