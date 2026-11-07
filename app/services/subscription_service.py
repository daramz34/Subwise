"""Subscription business logic. Every query is scoped to the logged-in user, so another
user's subscription is indistinguishable from one that doesn't exist (always a 404)."""
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Merchant, PaymentRecord, Plan, PriceHistory, Subscription, User
from app.schemas import (
    PaymentCreate, SubscriptionBulkIn, SubscriptionCreate, SubscriptionFilters, SubscriptionUpdate,
)
from app.services.audit import log_event
from app.services.category_service import get_usable_category
from app.services.tag_service import get_owned_tags

TWO_PLACES = Decimal("0.01")
SNAPSHOT_FIELDS = (
    "name", "merchant", "category_id", "amount", "currency", "billing_interval", "interval_count",
    "start_date", "next_renewal_date", "status", "trial_end_date", "trial_converts_amount",
    "commitment_end_date", "is_shared", "my_share_percent", "cancelled_on", "archived_at",
    "website_url", "cancel_url", "notes",
)


class DuplicateSubscriptionError(Exception):
    """Raised when a similar subscription exists. The router turns it into the 409 body."""

    def __init__(self, similar_ids):
        self.similar_ids = similar_ids


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today(user: User) -> date:
    try:
        tz = ZoneInfo(user.timezone)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date()


def _snapshot(sub: Subscription) -> dict:
    return {field: getattr(sub, field) for field in SNAPSHOT_FIELDS}


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _get_owned(db: Session, user: User, subscription_id, *, include_archived: bool = False) -> Subscription:
    stmt = (
        select(Subscription)
        .options(selectinload(Subscription.tags), selectinload(Subscription.category))
        .where(Subscription.id == subscription_id, Subscription.user_id == user.id)
    )
    if not include_archived:
        stmt = stmt.where(Subscription.archived_at.is_(None))
    sub = db.scalar(stmt)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    return sub


def _check_plan_limit(db: Session, user: User, plan: Plan) -> None:
    limit = (plan.limits or {}).get("max_subscriptions")
    if limit is None:
        return
    count = db.scalar(
        select(func.count()).select_from(Subscription)
        .where(Subscription.user_id == user.id, Subscription.archived_at.is_(None))
    )
    if count >= limit:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your {plan.name} plan allows up to {limit} subscriptions. Upgrade to add more.",
        )


def _find_similar(db: Session, user: User, name: str, merchant: str | None) -> list:
    conditions = [func.lower(Subscription.name) == _normalise(name)]
    if merchant:
        conditions.append(func.lower(Subscription.merchant) == _normalise(merchant))
    return list(db.scalars(
        select(Subscription.id).where(
            Subscription.user_id == user.id, Subscription.archived_at.is_(None), or_(*conditions)
        )
    ))


def _match_merchant(db: Session, name: str, merchant: str | None):
    """Link to a known merchant (for cancel links, overlap detection) when the name matches one."""
    for candidate in (merchant, name):
        if candidate:
            found = db.scalar(select(Merchant.id).where(Merchant.normalized_name == _normalise(candidate)))
            if found is not None:
                return found
    return None


def _sync_cancelled_on(sub: Subscription, today: date) -> None:
    if sub.status == "cancelled":
        if sub.cancelled_on is None:
            sub.cancelled_on = today
    else:
        sub.cancelled_on = None


def _validate_rules(sub: Subscription) -> None:
    """Rules that depend on the final state of the subscription, not just one field."""
    if sub.status == "trial" and sub.trial_end_date is None:
        raise HTTPException(422, "trial_end_date is required when status is 'trial'")
    if not sub.is_shared and Decimal(sub.my_share_percent) != Decimal("100"):
        raise HTTPException(422, "my_share_percent must be 100 unless is_shared is true")
    if sub.start_date and sub.next_renewal_date and sub.next_renewal_date < sub.start_date:
        raise HTTPException(422, "next_renewal_date cannot be before start_date")


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"  # a search for "%" matches a literal percent sign, not everything


# --------------------------------------------------------------------------
# Create / read
# --------------------------------------------------------------------------
def create_subscription(db: Session, user: User, plan: Plan, data: SubscriptionCreate, *,
                        source: str = "manual", commit: bool = True, price_effective_date=None) -> Subscription:
    _check_plan_limit(db, user, plan)

    values = data.model_dump(exclude={"tag_ids", "acknowledge_duplicate"})
    if values["category_id"] is not None:
        get_usable_category(db, user, values["category_id"])
    tags = get_owned_tags(db, user, data.tag_ids)

    if not data.acknowledge_duplicate:
        similar = _find_similar(db, user, data.name, data.merchant)
        if similar:
            raise DuplicateSubscriptionError(similar)

    today = _today(user)
    sub = Subscription(
        user_id=user.id,
        source=source,
        merchant_id=_match_merchant(db, data.name, data.merchant),
        last_confirmed_active_at=_now(),
        **values,
    )
    sub.tags = tags
    _sync_cancelled_on(sub, today)
    db.add(sub)
    db.flush()  # assigns sub.id

    # The first price on record, so history always starts with the price the user entered
    db.add(PriceHistory(
        subscription_id=sub.id, amount=sub.amount, previous_amount=None, currency=sub.currency,
        effective_date=price_effective_date or sub.start_date or today,
        source="manual" if source == "manual" else "import",
    ))
    log_event(db, user.id, "subscription", sub.id, "create", new=_snapshot(sub))
    if commit:
        db.commit()
        db.refresh(sub)
    else:
        db.flush()  # the caller commits, so a batch is all-or-nothing
    return sub


def get_subscription(db: Session, user: User, subscription_id) -> Subscription:
    return _get_owned(db, user, subscription_id, include_archived=True)


def list_subscriptions(db: Session, user: User, f: SubscriptionFilters):
    base = select(Subscription).where(Subscription.user_id == user.id)
    if not f.include_archived:
        base = base.where(Subscription.archived_at.is_(None))
    if f.status:
        base = base.where(Subscription.status == f.status)
    if f.category_id:
        base = base.where(Subscription.category_id == f.category_id)
    if f.tag_id:
        base = base.where(Subscription.tags.any(id=f.tag_id))
    if f.q:
        pattern = _like_pattern(f.q)
        base = base.where(or_(
            Subscription.name.ilike(pattern, escape="\\"),
            Subscription.merchant.ilike(pattern, escape="\\"),
        ))

    total = db.scalar(select(func.count()).select_from(base.subquery()))

    sort_columns = {
        "name": func.lower(Subscription.name),
        "amount": Subscription.amount,
        "next_renewal_date": Subscription.next_renewal_date,
        "created_at": Subscription.created_at,
    }
    column = sort_columns[f.sort]
    ordering = column.desc().nulls_last() if f.order == "desc" else column.asc().nulls_last()

    items = list(db.scalars(
        base.options(selectinload(Subscription.tags), selectinload(Subscription.category))
        .order_by(ordering, Subscription.id)  # id as tie-breaker keeps pages stable
        .offset((f.page - 1) * f.page_size)
        .limit(f.page_size)
    ))
    return items, total


# --------------------------------------------------------------------------
# Update / status / archive / bulk
# --------------------------------------------------------------------------
def update_subscription(db: Session, user: User, subscription_id, data: SubscriptionUpdate,
                        *, action: str = "update") -> Subscription:
    sub = _get_owned(db, user, subscription_id)
    changes = data.model_dump(exclude_unset=True)
    new_tag_ids = changes.pop("tag_ids", None)
    price_effective_date = changes.pop("price_effective_date", None)

    if changes.get("category_id") is not None:
        get_usable_category(db, user, changes["category_id"])
    new_tags = get_owned_tags(db, user, new_tag_ids) if new_tag_ids is not None else None

    if not changes and new_tags is None:
        return sub  # nothing to do

    old = _snapshot(sub)
    old_amount = Decimal(sub.amount).quantize(TWO_PLACES)
    old_currency = sub.currency

    for field, value in changes.items():
        setattr(sub, field, value)
    if changes.get("is_shared") is False and "my_share_percent" not in changes:
        sub.my_share_percent = Decimal("100.00")

    today = _today(user)
    _sync_cancelled_on(sub, today)
    try:
        _validate_rules(sub)
    except HTTPException:
        db.rollback()  # throw away the half-applied changes
        raise
    if new_tags is not None:
        sub.tags = new_tags

    # A real price (or currency) change adds a history row. Old rows are never edited.
    new_amount = Decimal(sub.amount).quantize(TWO_PLACES)
    if new_amount != old_amount or sub.currency != old_currency:
        db.add(PriceHistory(
            subscription_id=sub.id, amount=new_amount, currency=sub.currency,
            previous_amount=old_amount if sub.currency == old_currency else None,
            effective_date=price_effective_date or today, source="manual",
        ))

    log_event(db, user.id, "subscription", sub.id, action, old=old, new=_snapshot(sub))
    db.commit()
    db.refresh(sub)
    return sub


def set_status(db: Session, user: User, subscription_id, new_status: str) -> Subscription:
    return update_subscription(
        db, user, subscription_id, SubscriptionUpdate(status=new_status), action="status_change"
    )


def archive_subscription(db: Session, user: User, subscription_id) -> None:
    sub = _get_owned(db, user, subscription_id)
    old = _snapshot(sub)
    sub.archived_at = _now()
    log_event(db, user.id, "subscription", sub.id, "archive", old=old, new=_snapshot(sub))
    db.commit()


def bulk_apply(db: Session, user: User, data: SubscriptionBulkIn) -> tuple[int, int]:
    """Returns (updated, skipped). Ids that aren't the user's are skipped silently."""
    wanted = set(data.ids)
    subs = list(db.scalars(
        select(Subscription).where(
            Subscription.id.in_(wanted), Subscription.user_id == user.id,
            Subscription.archived_at.is_(None),
        )
    ))
    if data.action == "set_category":
        get_usable_category(db, user, data.category_id)

    status_for_action = {"activate": "active", "pause": "paused", "cancel": "cancelled"}
    today = _today(user)
    updated = 0
    for sub in subs:
        old = _snapshot(sub)
        if data.action in status_for_action:
            target = status_for_action[data.action]
            if sub.status == target:
                continue
            sub.status = target
            _sync_cancelled_on(sub, today)
        elif data.action == "archive":
            sub.archived_at = _now()
        else:  # set_category
            if sub.category_id == data.category_id:
                continue
            sub.category_id = data.category_id
        log_event(db, user.id, "subscription", sub.id, f"bulk_{data.action}", old=old, new=_snapshot(sub))
        updated += 1
    db.commit()
    return updated, len(wanted) - updated


# --------------------------------------------------------------------------
# Price history and payments
# --------------------------------------------------------------------------
def list_price_history(db: Session, user: User, subscription_id) -> list[PriceHistory]:
    sub = _get_owned(db, user, subscription_id, include_archived=True)
    return list(db.scalars(
        select(PriceHistory).where(PriceHistory.subscription_id == sub.id)
        .order_by(PriceHistory.effective_date, PriceHistory.recorded_at)
    ))


def create_payment(db: Session, user: User, subscription_id, data: PaymentCreate) -> PaymentRecord:
    sub = _get_owned(db, user, subscription_id)
    payment = PaymentRecord(
        subscription_id=sub.id, amount=data.amount, currency=data.currency,
        payment_date=data.payment_date, status=data.status,
        source="manual", verified=False,  # nothing typed in by hand counts as a verified payment
        external_reference=data.external_reference,
    )
    db.add(payment)
    db.flush()
    log_event(db, user.id, "payment", payment.id, "create", new={
        "subscription_id": sub.id, "amount": data.amount, "currency": data.currency,
        "payment_date": data.payment_date, "status": data.status,
    })
    db.commit()
    db.refresh(payment)
    return payment


def list_payments(db: Session, user: User, subscription_id) -> list[PaymentRecord]:
    sub = _get_owned(db, user, subscription_id, include_archived=True)
    return list(db.scalars(
        select(PaymentRecord).where(PaymentRecord.subscription_id == sub.id)
        .order_by(PaymentRecord.payment_date.desc(), PaymentRecord.created_at.desc())
    ))


# Public names for other services (the import service uses these)
def find_similar_ids(db: Session, user: User, name: str, merchant: str | None = None) -> list:
    return _find_similar(db, user, name, merchant)


snapshot_subscription = _snapshot