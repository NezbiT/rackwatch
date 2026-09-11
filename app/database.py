"""Async SQLAlchemy engine and session factory.

SQLite is the MVP store (one file, zero ops). The URL is swapped to
Postgres in the SaaS plan without touching routers — every query goes
through `async_session`.

The data directory is created on startup because Docker volume mounts
can arrive empty.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all RackWatch tables."""


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent folder of a SQLite file URL (posix or Windows)."""
    if "sqlite" not in url:
        return
    # sqlite+aiosqlite:///./data/x.db  |  sqlite+aiosqlite:////data/x.db
    if "////" in url:
        db_path = Path("/" + url.split("////", 1)[-1])
    elif ":///" in url:
        db_path = Path(url.split(":///", 1)[-1])
    else:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_sqlite_dir(settings.database_url)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url
    else {},
)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every boot."""
    from app import models  # noqa: F401  — register metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with async_session() as session:
        yield session
