"""Pytest config: async fixtures, test DB, client."""
from __future__ import annotations

# CRITICAL: set env BEFORE importing any app module so settings pick up test DB.
import os
os.environ["APP_TEST_MODE"] = "1"
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://posuhtik:posuhtik_dev@localhost:5432/posuhtik_test",
)
os.environ["DATABASE_URL_SYNC"] = "postgresql://posuhtik:posuhtik_dev@localhost:5432/posuhtik_test"

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.pool import NullPool

# Force fresh settings
from app.core import config as _cfg
_cfg.get_settings.cache_clear()
_cfg.settings = _cfg.get_settings()

from app.db.base import Base
import app.models  # noqa: F401  register mappers
from app.models.user import User
from app.models.product import Product
from app.models.enums import UserRole, ProductUnit
from app.core.time_utils import now_utc
from app.core.security import create_access_token
from app.core.config import settings


# Single event loop for entire session to avoid asyncpg cross-loop issues
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE audit_log, bottle_ledger, invoice_line_items, invoice_adjustments, invoices, "
            "payments, wallet_transactions, delivery_orders, "
            "subscription_schedule_overrides, subscriptions, "
            "route_stops, routes, otp_codes, notifications_log, "
            "revoked_tokens, "
            "addresses, products, users RESTART IDENTITY CASCADE"
        ))
        # Re-seed the singleton automation user (normally created by migration e5c1b7f2a3d8).
        await conn.execute(text("""
            INSERT INTO users (id, phone, name, role, is_active, approved_at, is_system, wallet_balance_paise, created_at)
            VALUES (gen_random_uuid(), '+910000000000', 'System (Automated)', 'ADMIN',
                    true, NOW(), true, 0, NOW())
            ON CONFLICT (phone) DO NOTHING
        """))
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as sess:
        yield sess


@pytest_asyncio.fixture(loop_scope="session")
async def client(engine, db):
    """HTTPX AsyncClient wired to FastAPI app with the test engine."""
    from app.db.session import get_db
    from app.main import app

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with session_maker() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise
            else:
                await s.commit()

    app.state._disable_scheduler = True
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(loop_scope="session")
async def admin_user(db: AsyncSession) -> User:
    u = User(phone="+919999999001", name="Admin", role=UserRole.ADMIN, is_active=True, approved_at=now_utc())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def customer_user(db: AsyncSession) -> User:
    u = User(phone="+919999999002", name="Cust", role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def delivery_user(db: AsyncSession) -> User:
    u = User(phone="+919999999003", name="DBoy", role=UserRole.DELIVERY, is_active=True, approved_at=now_utc())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def milk_product(db: AsyncSession) -> Product:
    p = Product(
        name="Cow Milk 500ml", sku="COW-MILK-500", unit=ProductUnit.LITRE,
        price_paise=3000, requires_bottle=True, active=True,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


def token_for(user: User) -> str:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return create_access_token(str(user.id), role)


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}
