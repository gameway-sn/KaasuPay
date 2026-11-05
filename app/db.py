"""Database connection: the engine, sessions, and the Base class for models.

In the project story this is the link from SRV-APP to SRV-DB (the vault).
Only code in this app talks to the database; browsers never do.
"""
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# SQLite only: allow a connection to be used from FastAPI's worker threads.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)

# A "session" is one conversation with the database (one per web request).
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Every model (table) inherits from this. Alembic reads Base.metadata."""


def get_db():
    """FastAPI dependency: open a session for one request, always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow() -> datetime:
    """Current time in UTC, without time-zone info.

    SQLite cannot store time zones, so we store plain UTC times everywhere
    and always compare against this function.
    """
    return datetime.now(UTC).replace(tzinfo=None)
