"""Inserts the reference data the app needs before anyone can register:
  - the Free and Plus plans
  - the default (system) categories

Safe to run as many times as you like: it only inserts what is missing.
Run from the project root:   python -m app.seed
"""
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Category, Plan

PLANS = [
    {
        "code": "free", "name": "AA Free", "price": Decimal("0.00"), "currency": "USD",
        "duration_days": None,
        "limits": {"max_subscriptions": 5, "ai_chat": False, "imports_per_month": 2},
    },
    {
        "code": "plus", "name": "AA Plus", "price": Decimal("5.00"), "currency": "USD",
        "duration_days": 30,
        "limits": {"max_subscriptions": None, "ai_chat": True, "imports_per_month": None},
    },
]

# (name, hex colour, icon)
CATEGORIES = [
    ("Entertainment", "#E4572E", "film"),
    ("Music", "#9B5DE5", "music"),
    ("Software", "#2E86AB", "code"),
    ("Cloud Storage", "#4ECDC4", "cloud"),
    ("News & Media", "#6C757D", "newspaper"),
    ("Education", "#F4A259", "book"),
    ("Health & Fitness", "#57CC99", "heart"),
    ("Gaming", "#EF476F", "gamepad"),
    ("Shopping", "#FFB400", "shopping-bag"),
    ("Utilities", "#8D99AE", "zap"),
    ("Other", "#ADB5BD", "tag"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        added_plans = 0
        for p in PLANS:
            if db.scalar(select(Plan).where(Plan.code == p["code"])) is None:
                db.add(Plan(**p))
                added_plans += 1

        added_categories = 0
        for name, color, icon in CATEGORIES:
            exists = db.scalar(
                select(Category).where(Category.user_id.is_(None), Category.name == name)
            )
            if exists is None:
                db.add(Category(user_id=None, name=name, color=color, icon=icon, is_default=True))
                added_categories += 1

        db.commit()
        print(f"Seed complete: {added_plans} plan(s) and {added_categories} categor(ies) added.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()