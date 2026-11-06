import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiter import reset_rate_limits
from app.database import Base, get_db
from app.main import app
from app.models import Plan


def _db_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0]


@pytest.fixture(scope="session")
def engine():
    url = settings.TEST_DATABASE_URL
    # Safety: the tests DROP every table, so refuse to touch anything that isn't clearly a test DB
    if not url or "test" not in _db_name(url).lower():
        pytest.exit(
            "Set TEST_DATABASE_URL in .env to a database whose name contains 'test' "
            "(e.g. .../subwise_test). Tests drop all tables, so they will not run on your real database.",
            returncode=2,
        )
    eng = create_engine(url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add_all([
            Plan(code="free", name="AA Free", price=0, currency="USD", duration_days=None,
                 limits={"max_subscriptions": 5, "ai_chat": False, "imports_per_month": 2}),
            Plan(code="plus", name="AA Plus", price=5, currency="USD", duration_days=30,
                 limits={"max_subscriptions": None, "ai_chat": True, "imports_per_month": None}),
        ])
        s.commit()
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    """Each test runs inside a transaction that is rolled back, so tests never affect each other."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    settings.RATE_LIMIT_ENABLED = False  # the rate-limit test switches it back on
    reset_rate_limits()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------- shared test users
PASSWORD = "Correct1Horse"


def _signup(client, email):
    r = client.post("/api/v1/auth/register",
                    json={"full_name": "Test User", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def alice(client):
    """Auth headers for a registered user."""
    return _signup(client, "alice@example.com")


@pytest.fixture
def bob(client):
    """Auth headers for a second user, used to prove users can't see each other's data."""
    return _signup(client, "bob@example.com")