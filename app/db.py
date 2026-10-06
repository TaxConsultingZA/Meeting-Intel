from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import get_settings
from .services.status_diagnostics import install_database_timings, measure


class Base(DeclarativeBase):
    """SQLAlchemy declarative base shared by all ORM models in this project."""


def _make_engine():
    """Create the async SQLAlchemy engine from the configured DATABASE_URL.

    Raises RuntimeError early (at import time) if the env var is missing so
    the server fails fast with a clear message instead of crashing on first query.
    """
    url = get_settings().asyncpg_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set — add it to your environment variables.")
    return create_async_engine(url, echo=False, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
install_database_timings(SessionLocal)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields a single AsyncSession per request and closes it on exit."""
    with measure("db_session_ms"):
        session = SessionLocal()
    async with session:
        yield session
