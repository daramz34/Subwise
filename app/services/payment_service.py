"""Plus-plan payments. Rules: the SERVER decides the price; capture is verified against PayPal's
answer (status, amount, currency); everything is idempotent; refunds/failures revoke the plan."""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PayPalOrder, PayPalWebhookEvent, Plan, UserEntitlement  # NAMES
from app.services import paypal_client
from app.services.audit import log_event
from app.services.paypal_client import PayPalError

logger = logging.getLogger(__name__)

HANDLED_EVENTS = {
    "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED", "PAYMENT.CAPTURE.DENIED",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ reading
def list_plans(db: Session) -> list[Plan]:
    return list(db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price)))


def get_entitlement(db: Session, user_id) -> UserEntitlement | None:
    return db.scalar(select(UserEntitlement).where(UserEntitlement.user_id == user_id))


def _is_live(ent: UserEntitlement | None) -> bool:
    return bool(ent and ent.status == "active" and (ent.expires_at is None or ent.expires_at > _now()))


def entitlement_info(db: Session, user) -> dict:
    ent = get_entitlement(db, user.id)
    if _is_live(ent):
        plan = db.get(Plan, ent.plan_id)
        return {"plan_code": plan.code, "status": "active", "expires_at": ent.expires_at}
    return {"plan_code": "free", "status": "active", "expires_at": None}


def list_orders(db: Session, user) -> list[dict]:
    rows = db.scalars(select(PayPalOrder).where(PayPalOrder.user_id == user.id)
                      .order_by(PayPalOrder.captured_at.desc().nullslast()))
    return [_order_out(o) for o in rows]


def _order_out(order: PayPalOrder) -> dict:
    return {"order_id": order.paypal_order_id, "status": order.status,
            "amount": f"{Decimal(order.amount):.2f}", "currency": order.currency,
            "captured_at": order.captured_at, "failure_reason": order.failure_reason}


# ------------------------------------------------------------------ entitlement
def _activate(db: Session, order: PayPalOrder) -> None:
    plan = db.get(Plan, order.plan_id)
    now = _now()
    ent = get_entitlement(db, order.user_id)
    if ent is None:
        ent = UserEntitlement(user_id=order.user_id, plan_id=plan.id)
        db.add(ent)
    ent.plan = plan  # set the relationship too, so the cached object is never stale
    ent.status = "active"
    ent.source_order_id = order.id
    ent.activated_at = now
    ent.expires_at = now + timedelta(days=plan.duration_days) if plan.duration_days else None
    ent.revoked_at = None
    ent.revoke_reason = None


def _revoke(db: Session, order: PayPalOrder, reason: str) -> None:
    ent = get_entitlement(db, order.user_id)
    if ent and ent.source_order_id == order.id and ent.status == "active":
        ent.status = "revoked"
        ent.revoked_at = _now()
        ent.revoke_reason = reason


def _complete_order(db: Session, order: PayPalOrder, capture_id: str | None) -> None:
    order.status = "completed"
    order.capture_id = capture_id
    order.captured_at = _now()
    order.failure_reason = None
    _activate(db, order)
    log_event(db, order.user_id, "payment", order.id, "payment_completed",
              new={"paypal_order_id": order.paypal_order_id, "amount": str(order.amount)})


def _fail(db: Session, order: PayPalOrder, reason: str) -> None:
    order.status = "failed"
    order.failure_reason = reason
    log_event(db, order.user_id, "payment", order.id, "payment_failed", new={"reason": reason})
    db.commit()


# ------------------------------------------------------------------ create
def create_order(db: Session, user, plan_code: str) -> dict:
    plan = db.scalar(select(Plan).where(Plan.code == plan_code, Plan.is_active.is_(True)))
    if plan is None:
        raise HTTPException(404, "Plan not found.")
    if Decimal(plan.price) <= 0:
        raise HTTPException(400, "This plan is free; there is nothing to pay.")
    if entitlement_info(db, user)["plan_code"] == plan.code:
        raise HTTPException(409, "You're already on this plan.")

    amount = f"{Decimal(plan.price):.2f}"          # price comes from OUR database, never the client
    idempotency_key = str(uuid.uuid4())
    try:
        result = paypal_client.create_order(
            amount=amount, currency=plan.currency,
            description=f"{settings.APP_NAME} {plan.name}",
            reference_id=plan.code, request_id=idempotency_key,
        )
    except PayPalError as e:
        raise HTTPException(502, str(e))
    if not result.get("id"):
        raise HTTPException(502, "PayPal returned an unexpected response.")

    order = PayPalOrder(user_id=user.id, plan_id=plan.id, paypal_order_id=result["id"],
                        idempotency_key=idempotency_key, amount=Decimal(amount),
                        currency=plan.currency, status="created")
    db.add(order)
    db.flush()
    log_event(db, user.id, "payment", order.id, "order_created", new={"paypal_order_id": order.paypal_order_id})
    db.commit()
    return {"order_id": order.paypal_order_id, "status": "created",
            "approve_url": paypal_client.approval_url(result)}


# ------------------------------------------------------------------ capture
def _extract_capture(result: dict) -> dict | None:
    try:
        return result["purchase_units"][0]["payments"]["captures"][0]
    except (KeyError, IndexError, TypeError):
        return None


def _amount_matches(order: PayPalOrder, amount: dict | None) -> bool:
    try:
        return (amount["currency_code"] == order.currency
                and Decimal(str(amount["value"])) == Decimal(order.amount))
    except (KeyError, TypeError, InvalidOperation):
        return False


def capture_order(db: Session, user, paypal_order_id: str) -> dict:
    order = db.scalar(
        select(PayPalOrder)
        .where(PayPalOrder.paypal_order_id == paypal_order_id, PayPalOrder.user_id == user.id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(404, "Order not found.")   # same answer for someone else's order
    if order.status == "completed":
        return {**_order_out(order), "plan_code": entitlement_info(db, user)["plan_code"]}
    if order.status in ("failed", "refunded"):
        raise HTTPException(409, f"This order is {order.status}. Start a new payment.")

    try:
        result = paypal_client.capture_order(order.paypal_order_id, request_id=order.idempotency_key)
    except PayPalError as e:
        if e.issue == "ORDER_ALREADY_CAPTURED":
            try:
                result = paypal_client.get_order(order.paypal_order_id)
            except PayPalError as e2:
                raise HTTPException(502, str(e2))
        elif e.issue == "ORDER_NOT_APPROVED":
            raise HTTPException(400, "The payment hasn't been approved in PayPal yet.")
        else:
            raise HTTPException(502, str(e))

    capture = _extract_capture(result)
    cap_status = (capture or {}).get("status")
    if cap_status == "PENDING":
        order.status = "approved"
        db.commit()
        raise HTTPException(409, "Your payment is pending. Plus will unlock when PayPal confirms it.")
    if result.get("status") != "COMPLETED" or cap_status != "COMPLETED":
        _fail(db, order, "capture_not_completed")
        raise HTTPException(402, "The payment wasn't completed.")
    if not _amount_matches(order, capture.get("amount")):
        logger.error("Captured amount mismatch for order %s", order.id)
        _fail(db, order, "amount_mismatch")
        raise HTTPException(400, "The paid amount didn't match the plan price.")

    _complete_order(db, order, capture.get("id"))
    db.commit()
    return {**_order_out(order), "plan_code": entitlement_info(db, user)["plan_code"]}


# ------------------------------------------------------------------ webhook
def _find_order(db: Session, resource: dict) -> PayPalOrder | None:
    def by(column, value):
        if not value:
            return None
        return db.scalar(select(PayPalOrder).where(column == value).with_for_update())

    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
    order = by(PayPalOrder.paypal_order_id, related) or by(PayPalOrder.capture_id, resource.get("id"))
    if order:
        return order
    for link in resource.get("links") or []:
        if link.get("rel") == "up" and link.get("href"):
            return by(PayPalOrder.capture_id, link["href"].rstrip("/").rsplit("/", 1)[-1])
    return None


def _apply_event(db: Session, rec: PayPalWebhookEvent, event: dict) -> str:
    etype = event["event_type"]
    if etype not in HANDLED_EVENTS:
        return "ignored"
    resource = event.get("resource") or {}
    order = _find_order(db, resource)
    if order is None:
        return "ignored"
    rec.paypal_order_id = order.paypal_order_id

    if etype == "PAYMENT.CAPTURE.COMPLETED":
        if order.status in ("created", "approved"):   # buyer paid but the browser never called capture
            if _amount_matches(order, resource.get("amount")):
                _complete_order(db, order, resource.get("id"))
            else:
                order.status = "failed"
                order.failure_reason = "amount_mismatch"
    elif etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        if order.status != "refunded":
            order.status = "refunded"
            order.refunded_at = _now()
            _revoke(db, order, "refunded")
            log_event(db, order.user_id, "payment", order.id, "payment_refunded", new={"event": etype})
    elif etype == "PAYMENT.CAPTURE.DENIED":
        if order.status not in ("refunded", "failed"):
            order.status = "failed"
            order.failure_reason = "capture_denied"
            _revoke(db, order, "payment_failed")
            log_event(db, order.user_id, "payment", order.id, "payment_failed", new={"event": etype})
    return "processed"


def handle_webhook(db: Session, headers, raw: bytes) -> dict:
    if not settings.PAYPAL_WEBHOOK_ID:
        raise HTTPException(503, "Webhook isn't configured.")
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid payload.")
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        raise HTTPException(400, "Invalid payload.")

    try:
        valid = paypal_client.verify_webhook(headers, event)
    except PayPalError:
        raise HTTPException(503, "Couldn't verify the webhook right now.")  # PayPal will retry
    if not valid:
        raise HTTPException(400, "Invalid signature.")

    rec = db.scalar(select(PayPalWebhookEvent).where(PayPalWebhookEvent.event_id == event["id"]))
    if rec and rec.status in ("processed", "ignored"):
        return {"detail": "Already handled."}          # idempotency: same event_id twice = no-op
    if rec:
        rec.attempts += 1
    else:
        resource = event.get("resource") or {}
        rec = PayPalWebhookEvent(
            event_id=event["id"], event_type=event["event_type"], status="received", attempts=1,
            received_at=_now(),
            # trimmed on purpose: no payer name/email is stored
            payload={"id": event["id"], "event_type": event["event_type"],
                     "resource_id": resource.get("id"), "resource_status": resource.get("status")},
        )
        db.add(rec)
    db.commit()

    try:
        outcome = _apply_event(db, rec, event)
        rec.status = outcome
        rec.processed_at = _now()
        rec.error_message = None
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Webhook processing failed for event %s", event["id"])
        rec = db.scalar(select(PayPalWebhookEvent).where(PayPalWebhookEvent.event_id == event["id"]))
        rec.status = "failed"
        rec.error_message = "Processing error"
        db.commit()
        raise HTTPException(500, "Processing error.")  # PayPal retries failed deliveries
    return {"detail": "ok"}