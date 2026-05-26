"""Historical price lookup (Phase 2B.5).

`get_price_at(product_id, date)` returns the price that was effective on
the given date. Used by the nightly order generation job so that each
DeliveryOrder row locks in the price valid on its delivery_date.

Priority:
  1. Latest `product_price_history.effective_from <= date` (if any)
  2. Fallback to `products.price_paise` (for edge cases)
"""
from __future__ import annotations
from datetime import date
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory


async def get_price_at(db: AsyncSession, product_id: uuid.UUID, on_date: date) -> int:
    stmt = (
        select(ProductPriceHistory.price_paise)
        .where(
            ProductPriceHistory.product_id == product_id,
            ProductPriceHistory.effective_from <= on_date,
        )
        .order_by(ProductPriceHistory.effective_from.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return int(row)
    prod_price = (await db.execute(
        select(Product.price_paise).where(Product.id == product_id)
    )).scalar_one_or_none()
    return int(prod_price or 0)
