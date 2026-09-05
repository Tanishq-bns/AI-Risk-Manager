"""SQLAlchemy 2.0 asynchronous database session and engine management.

Supports both zero-docker local execution via SQLite (aiosqlite) and production
deployments via PostgreSQL (asyncpg).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from risk_manager.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 ORM models."""
    pass


def create_engine_and_sessionmaker(
    database_url: str | None = None,
    echo: bool | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create and configure AsyncEngine and async_sessionmaker based on database URL."""
    settings = get_settings()
    url = database_url or settings.DATABASE_URL
    is_echo = echo if echo is not None else settings.DB_ECHO

    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {"echo": is_echo}

    # SQLite-specific configuration
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args

        # Use StaticPool for in-memory databases to preserve state across connections
        if ":memory:" in url:
            engine_kwargs["poolclass"] = StaticPool
        else:
            engine_kwargs["poolclass"] = NullPool
    else:
        # PostgreSQL pool configuration
        engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
        engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

    engine = create_async_engine(url, **engine_kwargs)

    # Enable foreign keys and performance optimizations for SQLite
    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            if ":memory:" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    return engine, session_factory


# Default application engine and sessionmaker
engine, async_session_factory = create_engine_and_sessionmaker()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone scripts, workers, and tests."""
    factory = session_factory or async_session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Create all tables declared in Base metadata."""
    # Ensure all models are imported before creating tables
    import risk_manager.db.models  # noqa: F401

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db(target_engine: AsyncEngine | None = None) -> None:
    """Drop all tables declared in Base metadata (useful for test isolation)."""
    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
