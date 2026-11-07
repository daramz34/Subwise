"""Date arithmetic for billing cycles. Pure Python, no dependencies."""
import calendar
from datetime import date, timedelta


def add_months(d: date, months: int) -> date:
    index = d.month - 1 + months
    year = d.year + index // 12
    month = index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])  # Jan 31 + 1 month = Feb 28/29
    return date(year, month, day)


def add_interval(d: date, interval: str, count: int = 1) -> date:
    if interval == "day":
        return d + timedelta(days=count)
    if interval == "week":
        return d + timedelta(weeks=count)
    if interval == "month":
        return add_months(d, count)
    if interval == "year":
        return add_months(d, 12 * count)
    raise ValueError(f"Unknown interval: {interval}")


def next_renewal_from(last_charge: date | None, interval: str, today: date, count: int = 1) -> date | None:
    """The first renewal date after today, counting forward from the last known charge.
    Always counts from the original date (not from the previous result), so a subscription
    billed on the 31st doesn't drift to the 28th forever."""
    if last_charge is None:
        return None
    if last_charge > today:
        return last_charge
    for step in range(1, 5000):
        candidate = add_interval(last_charge, interval, count * step)
        if candidate > today:
            return candidate
    return None