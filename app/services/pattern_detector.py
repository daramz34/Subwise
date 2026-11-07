"""Finds subscription-like charges in a list of transactions. Pure Python, no dependencies.

A group of charges is treated as a subscription when it has the same merchant, a regular
gap (about a week, month or year) and a stable price. Price increases are allowed.
Quarterly and irregular charges are deliberately NOT detected."""
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from app.services.csv_parser import Transaction

INTERVALS = {"week": (6, 8), "month": (26, 35), "year": (350, 380)}
MIN_REGULAR_SHARE = 0.7
MAX_PRICE_SPREAD = Decimal("0.5")      # (max - min) / median
MAX_LATEST_JUMP = Decimal("0.15")      # the last two charges must be within 15%
MAX_CANDIDATES = 100

NOISE = {
    "pos", "purchase", "payment", "pay", "card", "debit", "ach", "web", "transfer", "trf", "nip", "ref",
    "txn", "transaction", "online", "recurring", "sq", "paypal", "to", "from", "via", "the", "inc", "ltd",
    "llc", "limited", "plc", "bill", "billing", "subscription", "sub", "charge", "visa", "mastercard", "mc",
    "stripe", "aso", "atm", "ussd", "ibank", "mobile", "ng", "lag", "lagos", "usa", "us", "gb", "uk", "ca",
    "com", "www",
}


@dataclass
class Candidate:
    name: str
    amount: Decimal
    currency: str | None
    interval: str
    last_date: object
    occurrences: int
    confidence: Decimal
    field_confidence: dict


def merchant_key(description: str) -> str:
    """'NETFLIX.COM 8665797172 CA' and 'NETFLIX.COM 5551234567 CA' both become 'netflix'."""
    s = description.lower()
    s = re.sub(r"https?://\S+|www\.\S+", " ", s)
    s = re.sub(r"\.(com|net|org|io|co|ng|uk|app)\b", " ", s)
    s = re.sub(r"[^a-z&' ]+", " ", s)
    tokens = [t for t in s.split() if t not in NOISE and len(t) > 1]
    return " ".join(tokens[:3])


def _outflows(transactions: list[Transaction]) -> list[tuple[Transaction, Decimal]]:
    """Statements mark money out as negative; if nothing is negative, every row is a charge."""
    has_negative = any(t.amount < 0 for t in transactions)
    out = []
    for t in transactions:
        if has_negative and t.amount < 0:
            out.append((t, -t.amount))
        elif not has_negative and t.amount > 0:
            out.append((t, t.amount))
    return out


def _classify(gaps: list[int]) -> tuple[str | None, float]:
    mid = median(gaps)
    for interval, (low, high) in INTERVALS.items():
        if low <= mid <= high:
            regular = sum(low <= g <= high for g in gaps) / len(gaps)
            return interval, regular
    return None, 0.0


def detect_recurring(transactions: list[Transaction]) -> list[Candidate]:
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for txn, positive in _outflows(transactions):
        key = merchant_key(txn.description)
        if key:
            groups[(key, txn.currency)].append((txn.date, positive))

    found: list[Candidate] = []
    for (key, currency), entries in groups.items():
        entries = sorted(set(entries))                  # drops exact duplicate rows
        if len(entries) < 2:
            continue
        dates = [d for d, _ in entries]
        amounts = [a for _, a in entries]

        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue
        interval, regular = _classify(gaps)
        if interval is None or regular < MIN_REGULAR_SHARE:
            continue

        mid_amount = median(amounts)
        if mid_amount <= 0 or (max(amounts) - min(amounts)) / mid_amount > MAX_PRICE_SPREAD:
            continue
        if len(amounts) >= 3 and abs(amounts[-1] - amounts[-2]) / amounts[-2] > MAX_LATEST_JUMP:
            continue

        latest = amounts[-1]
        stable = sum(abs(a - latest) / latest <= Decimal("0.05") for a in amounts) / len(amounts)
        occurrence_score = min(len(entries), 6) / 6
        confidence = min(0.97, 0.15 + 0.35 * occurrence_score + 0.25 * regular + 0.25 * stable)

        found.append(Candidate(
            name=" ".join(w.capitalize() for w in key.split()),
            amount=latest.quantize(Decimal("0.01")),
            currency=currency,
            interval=interval,
            last_date=dates[-1],
            occurrences=len(entries),
            confidence=Decimal(str(round(confidence, 3))),
            field_confidence={
                "name": 0.6,
                "amount": round(0.5 + 0.5 * stable, 3),
                "interval": round(regular * (0.5 + 0.5 * min(len(entries), 4) / 4), 3),
            },
        ))

    found.sort(key=lambda c: (c.confidence, c.amount), reverse=True)
    return found[:MAX_CANDIDATES]