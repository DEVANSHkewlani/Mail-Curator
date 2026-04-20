"""
database.py — Async SQLAlchemy engine & session factory for The Curator Mail.

The DATABASE_URL is read from the environment variable DATABASE_URL.
Default: a local Postgres instance (suitable for docker-compose).

Tables are created automatically on startup via Base.metadata.create_all().
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

# ─── Engine ───────────────────────────────────────────────────────────────────

_RAW_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://curator:curator@localhost:5432/curator_mail",
)

# Convert standard postgres:// URLs (Render/Heroku) to asyncpg-compatible URLs
if _RAW_DB_URL.startswith("postgres://"):
    DATABASE_URL = _RAW_DB_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif _RAW_DB_URL.startswith("postgresql://") and "+asyncpg" not in _RAW_DB_URL:
    DATABASE_URL = _RAW_DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _RAW_DB_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # Reconnect on stale connections
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ─── Dependency ───────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session


# ─── Init ─────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables on first startup (idempotent)."""
    async with engine.begin() as conn:
        # Import models to ensure they are registered on Base.metadata
        from . import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE send_logs ADD COLUMN IF NOT EXISTS stopped BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE send_results ADD COLUMN IF NOT EXISTS message_id TEXT"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_send_results_message_id ON send_results (message_id)"))
