from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import ensure_sqlite_path_exists, settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


ensure_sqlite_path_exists(settings.database_url)
engine = create_async_engine(settings.database_url, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create database tables if they do not exist."""

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
