"""Analytics: monthly/yearly cost, upcoming renewals, price changes.

Rules: only active + trial count; archived excluded; my_share_percent applied;
totals are kept per currency (never summed across currencies).
"""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, PriceHistory, Subscription, User

COUNTED_STATUSES = ("active", "trial")
UNITS_PER_MONTH = {
    "day": Decimal(365) / Decimal(12),
    "week": Decimal(52) / Decimal(12),
    "month": Decimal(1),
    "year": Decimal(1) / Decimal(12),
}
TWO = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    return x.quantize(TWO)


def today_for(user: User) -> date:
    try:
        return datetime.now(ZoneInfo(user.timezone or "UTC")).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _step(anchor: date, unit: str, n: int, k: int) -> date:
    """anchor + k billing periods (always computed from the anchor, so Jan 31 doesn't drift)."""
    if unit == "day":
        return anchor + timedelta(days=n * k)
    if unit == "week":
        return anchor + timedelta(weeks=n * k)
    if unit == "month":
        return _add_months(anchor, n * k)
    return _add_months(anchor, 12 * n * k)


def next_occurrence(anchor: date, unit: str, n: int, today: date) -> date:
    k = 0
    d = anchor
    while d < today and k < 20000:
        k += 1
        d = _step(anchor, unit, n, k)
    return d


def monthly_equivalent(amount: Decimal, unit: str, interval_count: int, share_percent: Decimal | None) -> Decimal:
    share = (share_percent if share_percent is not None else Decimal(100)) / Decimal(100)
    per_period = Decimal(amount) / Decimal(max(interval_count or 1, 1))
    return per_period * UNITS_PER_MONTH[unit] * share


def _effective_amount(sub: Subscription) -> Decimal:
    if sub.status == "trial" and sub.trial_converts_amount is not None:
        return Decimal(sub.trial_converts_amount)
    return Decimal(sub.amount)


def _user_subs(db: Session, user: User) -> list[Subscription]:
    return list(db.scalars(
        select(Subscription).where(Subscription.user_id == user.id, Subscription.archived_at.is_(None))
    ))


def get_overview(db: Session, user: User, days: int = 30) -> dict:
    today = today_for(user)
    subs = [s for s in _user_subs(db, user) if s.status in COUNTED_STATUSES]

    cat_ids = {s.category_id for s in subs if s.category_id}
    cat_names = {}
    if cat_ids:
        cat_names = {c.id: c.name for c in db.scalars(select(Category).where(Category.id.in_(cat_ids)))}

    totals = defaultdict(lambda: {"monthly": Decimal(0), "count": 0})
    by_cat = defaultdict(lambda: defaultdict(lambda: Decimal(0)))
    upcoming = []
    horizon = today + timedelta(days=days)

    for s in subs:
        monthly = monthly_equivalent(_effective_amount(s), s.billing_interval, s.interval_count, s.my_share_percent)
        cur = s.currency
        totals[cur]["monthly"] += monthly
        totals[cur]["count"] += 1
        by_cat[cur][cat_names.get(s.category_id, "Uncategorised")] += monthly

        if s.next_renewal_date:
            due = next_occurrence(s.next_renewal_date, s.billing_interval, s.interval_count or 1, today)
            if today <= due <= horizon:
                upcoming.append({
                    "subscription_id": str(s.id), "name": s.name, "amount": _q(_effective_amount(s)),
                    "currency": cur, "renewal_date": due, "days_until": (due - today).days,
                    "status": s.status,
                })

    upcoming.sort(key=lambda r: (r["renewal_date"], r["name"].lower()))
    return {
        "as_of": today,
        "subscription_count": len(subs),
        "totals": [
            {"currency": cur, "monthly": _q(v["monthly"]), "yearly": _q(v["monthly"] * 12), "count": v["count"]}
            for cur, v in sorted(totals.items())
        ],
        "by_category": [
            {"currency": cur, "category": name, "monthly": _q(v)}
            for cur, cats in sorted(by_cat.items())
            for name, v in sorted(cats.items(), key=lambda kv: -kv[1])
        ],
        "upcoming_renewals": upcoming,
    }


def get_price_changes(db: Session, user: User) -> list[dict]:
    subs = {s.id: s for s in _user_subs(db, user)}
    if not subs:
        return []
    rows = db.scalars(
        select(PriceHistory).where(PriceHistory.subscription_id.in_(list(subs)))
        .order_by(PriceHistory.subscription_id, PriceHistory.effective_date, PriceHistory.recorded_at)
    ).all()

    grouped = defaultdict(list)
    for r in rows:
        grouped[r.subscription_id].append(r)

    changes = []
    for sub_id, history in grouped.items():
        sub = subs[sub_id]
        for prev, cur in zip(history, history[1:]):
            if prev.currency != cur.currency or Decimal(prev.amount) == Decimal(cur.amount) or Decimal(prev.amount) == 0:
                continue  # never compare across currencies
            diff = Decimal(cur.amount) - Decimal(prev.amount)
            yearly = monthly_equivalent(diff, sub.billing_interval, sub.interval_count, sub.my_share_percent) * 12
            changes.append({
                "subscription_id": str(sub_id), "name": sub.name, "currency": cur.currency,
                "old_amount": _q(Decimal(prev.amount)), "new_amount": _q(Decimal(cur.amount)),
                "change_percent": _q(diff / Decimal(prev.amount) * 100),
                "yearly_impact": _q(yearly), "effective_date": cur.effective_date,
            })
    changes.sort(key=lambda c: c["effective_date"], reverse=True)
    return changes