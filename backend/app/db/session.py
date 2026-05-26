"""Async SQLAlchemy 2.0 session factory."""
from typing import AsyncGenerator
import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Use NullPool when running under pytest to avoid cross-event-loop issues with asyncpg.
_is_pytest = "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("APP_TEST_MODE") == "1"

_engine_kwargs: dict = {"echo": False, "pool_pre_ping": False}
if _is_pytest:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update({"pool_size": 5, "max_overflow": 15, "pool_pre_ping": True})

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
