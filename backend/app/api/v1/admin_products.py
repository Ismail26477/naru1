"""Admin product management + price-change history (Phase 2B.5)."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.user import User
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory
from app.models.enums import ProductUnit
from app.models.subscription import Subscription
from app.models.enums import SubscriptionStatus
from app.services import audit_service
from app.core.time_utils import now_utc, today_ist


router = APIRouter(
    prefix="/admin",
    tags=["admin-products"],
    dependencies=[Depends(require_admin)],
)


# ---------- schemas ----------

class ProductCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    sku: str = Field(..., min_length=1, max_length=40)
    unit: str = Field(..., description="ml | l | g | kg | piece etc.")
    price_paise: int = Field(..., gt=0)
    requires_bottle: bool = False
    description: str | None = Field(None, max_length=2000)
    image_url: str | None = Field(None, max_length=500)


class ProductUpdateBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    unit: str | None = None
    requires_bottle: bool | None = None
    description: str | None = Field(None, max_length=2000)
    image_url: str | None = Field(None, max_length=500)
    active: bool | None = None


class PriceChangeBody(BaseModel):
    new_price_paise: int = Field(..., gt=0)
    effective_from: date
    reason: str = Field(..., min_length=10, max_length=500)


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    sku: str
    unit: str
    price_paise: int
    requires_bottle: bool
    description: str | None
    image_url: str | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PriceHistoryRow(BaseModel):
    id: uuid.UUID
    price_paise: int
    effective_from: date
    changed_by: uuid.UUID | None
    changed_by_name: str | None
    reason: str | None
    created_at: datetime


class ProductDetail(ProductOut):
    last_price_change_date: date | None
    active_subscribers_count: int
    price_history: list[PriceHistoryRow]


class ProductListRow(ProductOut):
    last_price_change_date: date | None


# ---------- helpers ----------

async def _get_product_or_404(db: AsyncSession, pid: uuid.UUID) -> Product:
    p = (await db.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="product not found")
    return p


def _product_to_out(p: Product) -> dict[str, Any]:
    return {
        "id": str(p.id), "name": p.name, "sku": p.sku,
        "unit": p.unit.value if hasattr(p.unit, "value") else str(p.unit),
        "price_paise": p.price_paise,
        "requires_bottle": p.requires_bottle,
        "description": p.description,
        "image_url": p.image_url,
        "active": p.active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _product_response(p: Product) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "sku": p.sku,
        "unit": p.unit.value if hasattr(p.unit, "value") else str(p.unit),
        "price_paise": p.price_paise,
        "requires_bottle": p.requires_bottle,
        "description": p.description,
        "image_url": p.image_url,
        "active": p.active,
        "created_at": p.created_at,
    }


# ---------- list ----------

@router.get("/products", response_model=list[ProductListRow])
async def list_products(
    active: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Product)
    if active is not None:
        stmt = stmt.where(Product.active.is_(active))
    stmt = stmt.order_by(Product.name.asc())
    prods = (await db.execute(stmt)).scalars().all()
    if not prods:
        return []
    ids = [p.id for p in prods]
    last_rows = (await db.execute(
        select(ProductPriceHistory.product_id, func.max(ProductPriceHistory.effective_from))
        .where(ProductPriceHistory.product_id.in_(ids))
        .group_by(ProductPriceHistory.product_id)
    )).all()
    last_map = {r[0]: r[1] for r in last_rows}
    return [
        ProductListRow(**_product_response(p), last_price_change_date=last_map.get(p.id))
        for p in prods
    ]


# ---------- detail ----------

@router.get("/products/{product_id}", response_model=ProductDetail)
async def product_detail(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    p = await _get_product_or_404(db, product_id)

    hist = (await db.execute(
        select(ProductPriceHistory)
        .where(ProductPriceHistory.product_id == product_id)
        .order_by(ProductPriceHistory.effective_from.desc(), ProductPriceHistory.created_at.desc())
    )).scalars().all()
    actor_ids = [h.changed_by for h in hist if h.changed_by]
    actors = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
    } if actor_ids else {}

    active_subs = int((await db.execute(
        select(func.count(Subscription.id)).where(
            Subscription.product_id == product_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )).scalar_one() or 0)

    return ProductDetail(
        **_product_response(p),
        last_price_change_date=(hist[0].effective_from if hist else None),
        active_subscribers_count=active_subs,
        price_history=[
            PriceHistoryRow(
                id=h.id, price_paise=h.price_paise, effective_from=h.effective_from,
                changed_by=h.changed_by,
                changed_by_name=(actors[h.changed_by].name if h.changed_by in actors else None),
                reason=h.reason, created_at=h.created_at,
            )
            for h in hist
        ],
    )


# ---------- create ----------

@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    body: ProductCreateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        unit = ProductUnit(body.unit)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid unit '{body.unit}'")
    # Unique SKU
    dup = (await db.execute(select(Product).where(Product.sku == body.sku))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail={"code": "sku_conflict", "message": "SKU already in use"})

    p = Product(
        name=body.name, sku=body.sku, unit=unit,
        price_paise=body.price_paise, requires_bottle=body.requires_bottle,
        description=body.description, image_url=body.image_url, active=True,
    )
    db.add(p)
    await db.flush()

    # Seed the initial history row
    db.add(ProductPriceHistory(
        product_id=p.id, price_paise=body.price_paise,
        effective_from=today_ist(), changed_by=admin.id,
        reason="Initial price at product creation",
    ))
    await db.flush()

    await audit_service.log_action(
        db, actor=admin, action="product.create",
        entity_type="product", entity_id=str(p.id),
        before_state=None,
        after_state=_product_to_out(p),
        request=request,
    )
    return ProductOut(**_product_response(p))


# ---------- update metadata ----------

@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_product_or_404(db, product_id)
    before = _product_to_out(p)
    if body.unit is not None:
        try:
            p.unit = ProductUnit(body.unit)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid unit '{body.unit}'")
    for field in ("name", "requires_bottle", "description", "image_url", "active"):
        v = getattr(body, field)
        if v is not None:
            setattr(p, field, v)
    await db.flush()
    after = _product_to_out(p)
    await audit_service.log_action(
        db, actor=admin, action="product.update",
        entity_type="product", entity_id=str(p.id),
        before_state=before, after_state=after, request=request,
    )
    return ProductOut(**_product_response(p))


# ---------- price change ----------

@router.post("/products/{product_id}/price-change", response_model=ProductDetail, status_code=201)
async def price_change(
    product_id: uuid.UUID,
    body: PriceChangeBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_product_or_404(db, product_id)

    if body.effective_from < today_ist():
        raise HTTPException(
            status_code=400,
            detail={"code": "cannot_backdate", "message": "effective_from must be today or a future date"},
        )

    before = {"price_paise": p.price_paise}

    # Record in history
    row = ProductPriceHistory(
        product_id=p.id, price_paise=body.new_price_paise,
        effective_from=body.effective_from, changed_by=admin.id, reason=body.reason,
    )
    db.add(row)

    applied_immediately = body.effective_from <= today_ist()
    if applied_immediately:
        p.price_paise = body.new_price_paise

    await db.flush()

    await audit_service.log_action(
        db, actor=admin, action="product.price_change",
        entity_type="product", entity_id=str(p.id),
        before_state=before,
        after_state={
            "price_paise": p.price_paise,
            "new_price_paise": body.new_price_paise,
            "effective_from": body.effective_from.isoformat(),
            "applied_immediately": applied_immediately,
            "history_id": str(row.id),
        },
        reason=body.reason, request=request,
    )
    return await product_detail(product_id, db)


@router.get("/products/{product_id}/price-history", response_model=list[PriceHistoryRow])
async def price_history(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_product_or_404(db, product_id)
    hist = (await db.execute(
        select(ProductPriceHistory)
        .where(ProductPriceHistory.product_id == product_id)
        .order_by(ProductPriceHistory.effective_from.desc(), ProductPriceHistory.created_at.desc())
    )).scalars().all()
    actor_ids = [h.changed_by for h in hist if h.changed_by]
    actors = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
    } if actor_ids else {}
    return [
        PriceHistoryRow(
            id=h.id, price_paise=h.price_paise, effective_from=h.effective_from,
            changed_by=h.changed_by,
            changed_by_name=(actors[h.changed_by].name if h.changed_by in actors else None),
            reason=h.reason, created_at=h.created_at,
        )
        for h in hist
    ]
