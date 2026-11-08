"""python -m app.run_notifications  ->  creates alerts for every user. Safe to run repeatedly."""
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.services import notification_service


def main() -> None:
    with SessionLocal() as db:
        total = 0
        for user in db.scalars(select(User)).all():
            total += notification_service.generate_for_user(db, user)
        print(f"Created {total} notification(s).")


if __name__ == "__main__":
    main()