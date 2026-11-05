"""Shared test setup.

Every test gets a brand-new, empty in-memory database, so tests never touch
kaasupay.db and never affect each other.
"""
import os

# Set BEFORE importing the app: settings are read when app.config is imported.
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-at-least-32-characters"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

TEST_PASSWORD = "Passw0rd!"


@pytest.fixture
def db():
    # StaticPool + "sqlite://" = one in-memory database shared by the test and the app.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    # Make the app use our test database instead of the real one.
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db):
    """Create a ready-to-log-in user directly in the database."""

    def _make(phone: str, role: str = Role.CUSTOMER, full_name: str = "Test User") -> User:
        user = User(phone=phone, full_name=full_name, role=role,
                    password_hash=hash_password(TEST_PASSWORD), phone_verified=True)
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def login(client):
    """Log in through the real /login form. Returns the response."""

    def _login(phone: str, password: str = TEST_PASSWORD):
        return client.post("/login", data={"phone": phone, "password": password}, follow_redirects=False)

    return _login
