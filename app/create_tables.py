"""Temporary: creates every table. Replace with Alembic migrations before deployment.
Run:  python -m app.create_tables
"""
import app.models  # noqa: F401  (importing registers every table on Base)
from app.database import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Tables created.")