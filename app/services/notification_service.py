"""In-app notifications. Alerts are generated when the user opens their list (or by
`python -m app.run_notifications` for everyone). Every alert has a dedupe_key, and
(user_id, dedupe_key) is unique in the database, so reruns can never duplicate an alert."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Notification, NotificationPreference, Subscription
from app.services import analytics_service

TRIAL_WARN_DAYS = 3
PRICE_LOOKBACK_DAYS = 30
DEFAULT_RENEWAL_DAYS = [1, 3, 7]
PREF_FIELDS = ("renewal_days_before", "in_app_enabled", "email_enabled", "trial_alerts_enabled",
               "price_alerts_enabled", "weekly_digest_enabled", "weekly_digest_day")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ preferences
def get_preferences(db: Session, user) -> NotificationPreference:
    prefs = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user.id))
    if prefs is None:
        prefs = NotificationPreference(
            user_id=user.id, renewal_days_before=list(DEFAULT_RENEWAL_DAYS), in_app_enabled=True,
            email_enabled=False, trial_alerts_enabled=True, price_alerts_enabled=True,
            weekly_digest_enabled=False, weekly_digest_day=0, updated_at=_now())
        db.add(prefs)
        db.flush()
    return prefs


def prefs_out(prefs: NotificationPreference) -> dict:
    return {f: getattr(prefs, f) for f in PREF_FIELDS}


def update_preferences(db: Session, user, changes: dict) -> dict:
    prefs = get_preferences(db, user)
    changes = {k: v for k, v in changes.items() if k in PREF_FIELDS and v is not None}
    if "renewal_days_before" in changes:
        days = changes["renewal_days_before"]
        if (not isinstance(days, list) or len(days) > 10
                or any(not isinstance(d, int) or isinstance(d, bool) or d < 0 or d > 90 for d in days)):
            raise HTTPException(422, "renewal_days_before must be up to 10 whole numbers between 0 and 90.")
        changes["renewal_days_before"] = sorted(set(days))
    for field, value in changes.items():
        setattr(prefs, field, value)
    prefs.updated_at = _now()
    db.commit()
    return prefs_out(prefs)


# ------------------------------------------------------------------ generation
def _add(db: Session, user, existing: set, *, ntype: str, key: str, title: str, message: str, sub_id) -> bool:
    if key in existing:
        return False
    now = _now()
    note = Notification(user_id=user.id, subscription_id=sub_id, notification_type=ntype, channel="in_app",
                        title=title[:200], message=message, dedupe_key=key[:150],
                        scheduled_for=now, sent_at=now, created_at=now)
    try:
        with db.begin_nested():          # savepoint: a lost race on the unique key is not an error
            db.add(note)
            db.flush()
    except IntegrityError:
        existing.add(key)
        return False
    existing.add(key)
    return True


def _when(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


def generate_for_user(db: Session, user, today: date | None = None) -> int:
    prefs = get_preferences(db, user)
    if not prefs.in_app_enabled:
        db.commit()
        return 0
    today = today or analytics_service.today_for(user)
    subs = list(db.scalars(select(Subscription).where(
        Subscription.user_id == user.id, Subscription.archived_at.is_(None),
        Subscription.status.in_(("active", "trial")))))
    existing = set(db.scalars(select(Notification.dedupe_key).where(Notification.user_id == user.id)))
    thresholds = sorted({int(d) for d in (prefs.renewal_days_before or [])})
    created = 0

    for s in subs:
        amount = analytics_service._q(Decimal(s.amount))
        if s.status == "active" and s.next_renewal_date and thresholds:
            due = analytics_service.next_occurrence(
                s.next_renewal_date, s.billing_interval, s.interval_count or 1, today)
            days = (due - today).days
            eligible = [t for t in thresholds if days <= t]
            if days >= 0 and eligible:
                created += _add(
                    db, user, existing, ntype="renewal", sub_id=s.id,
                    key=f"renewal:{s.id}:{due.isoformat()}:{min(eligible)}",
                    title=f"{s.name} renews {_when(days)}",
                    message=f"{s.name} will charge {amount} {s.currency} on {due.isoformat()}.")
        if s.status == "trial" and prefs.trial_alerts_enabled and s.trial_end_date:
            days = (s.trial_end_date - today).days
            if 0 <= days <= TRIAL_WARN_DAYS:
                if s.trial_converts_amount is not None:
                    after = (f"It will then cost {analytics_service._q(Decimal(s.trial_converts_amount))} "
                             f"{s.currency}. Cancel before then if you don't want it.")
                else:
                    after = "Cancel before then if you don't want to be charged."
                created += _add(
                    db, user, existing, ntype="trial_ending", sub_id=s.id,
                    key=f"trial:{s.id}:{s.trial_end_date.isoformat()}",
                    title=f"{s.name} trial ends {_when(days)}",
                    message=f"Your {s.name} free trial ends on {s.trial_end_date.isoformat()}. {after}")

    if prefs.price_alerts_enabled:
        by_id = {str(s.id): s for s in subs}
        cutoff = today - timedelta(days=PRICE_LOOKBACK_DAYS)
        for c in analytics_service.get_price_changes(db, user):
            s = by_id.get(c["subscription_id"])
            if s is None or c["change_percent"] <= 0 or c["effective_date"] < cutoff:
                continue
            created += _add(
                db, user, existing, ntype="price_increase", sub_id=s.id,
                key=f"price:{s.id}:{c['effective_date'].isoformat()}:{c['new_amount']}",
                title=f"{s.name} price went up",
                message=(f"{s.name} changed from {c['old_amount']} to {c['new_amount']} {c['currency']} "
                         f"(+{c['change_percent']}%), about {c['yearly_impact']} {c['currency']} more per year "
                         f"(your share)."))
    db.commit()
    return created


# ------------------------------------------------------------------ reading
def _out(n: Notification) -> dict:
    return {"id": n.id, "subscription_id": n.subscription_id, "notification_type": n.notification_type,
            "channel": n.channel, "title": n.title, "message": n.message,
            "scheduled_for": n.scheduled_for, "sent_at": n.sent_at, "read_at": n.read_at}


def list_notifications(db: Session, user, unread_only: bool = False, limit: int = 50) -> dict:
    generate_for_user(db, user)
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread_count": unread, "items": [_out(n) for n in rows]}


def mark_read(db: Session, user, notification_id) -> dict:
    note = db.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id))
    if note is None:
        raise HTTPException(404, "Notification not found.")
    if note.read_at is None:
        note.read_at = _now()
        db.commit()
    return _out(note)