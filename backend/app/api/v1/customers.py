"""Customer-facing endpoints."""
from __future__ import annotations
from datetime import date
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User, Address
from app.models.subscription import Subscription, SubscriptionScheduleOverride
from app.models.product import Product
from app.models.delivery import DeliveryOrder
from app.models.billing import Invoice, WalletTransaction
from app.models.enums import SubscriptionStatus
from app.middleware.auth import get_current_user, require_customer
from app.schemas.user import UserOut, UpdateMeBody, AddressCreate, AddressOut
from app.schemas.product import ProductOut
from app.schemas.subscription import (
    SubscriptionCreate, SubscriptionUpdate, SubscriptionOut,
    ScheduleOverrideCreate, ScheduleOverrideOut,
)
from app.schemas.delivery import DeliveryOrderOut, InvoiceOut, InvoiceDetailOut, BottleBalanceOut, WalletOut
from app.services.cutoff_service import assert_modifiable
from app.services import bottle_service
from app.providers import get_geocoder

router = APIRouter(tags=["customer"])


# /me -----------------------------------------------------------------
@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateMeBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.name is not None:
        user.name = body.name
    if body.email is not None:
        user.email = body.email
    await db.flush()
    return user


# addresses
@router.get("/me/addresses", response_model=list[AddressOut])
async def list_addresses(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Address).where(Address.user_id == user.id))).scalars().all()
    return list(rows)


@router.post("/me/addresses", response_model=AddressOut, status_code=201)
async def add_address(body: AddressCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    geo = await get_geocoder().geocode(f"{body.line1}, {body.area}, {body.city} {body.pincode}")
    if body.is_default:
        await db.execute(update(Address).where(Address.user_id == user.id).values(is_default=False))
    addr = Address(
        user_id=user.id, line1=body.line1, line2=body.line2, area=body.area,
        city=body.city, pincode=body.pincode, is_default=body.is_default,
        lat=geo.lat, lng=geo.lng, geocoding_pending=geo.pending,
    )
    db.add(addr)
    await db.flush()
    return addr


# products
@router.get("/products", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Product).where(Product.active == True).order_by(Product.name))).scalars().all()  # noqa: E712
    return list(rows)


# subscriptions
@router.get("/me/subscriptions", response_model=list[SubscriptionOut])
async def my_subs(user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Subscription).where(Subscription.customer_id == user.id))).scalars().all()
    return list(rows)


@router.post("/me/subscriptions", response_model=SubscriptionOut, status_code=201)
async def create_sub(body: SubscriptionCreate, user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    prod = (await db.execute(select(Product).where(Product.id == body.product_id, Product.active == True))).scalar_one_or_none()  # noqa: E712
    if not prod:
        raise HTTPException(status_code=404, detail="product not found")
    sub = Subscription(
        customer_id=user.id, product_id=body.product_id, quantity=body.quantity,
        frequency=body.frequency, custom_days=body.custom_days,
        start_date=body.start_date, end_date=body.end_date,
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.flush()
    return sub


@router.patch("/me/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def update_sub(sub_id: uuid.UUID, body: SubscriptionUpdate, user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    sub = (await db.execute(select(Subscription).where(Subscription.id == sub_id, Subscription.customer_id == user.id))).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    for field in ("quantity", "frequency", "custom_days", "end_date", "status", "pause_from", "pause_until"):
        val = getattr(body, field)
        if val is not None:
            setattr(sub, field, val)
    await db.flush()
    return sub


@router.post("/me/subscriptions/{sub_id}/schedule-override", response_model=ScheduleOverrideOut, status_code=201)
async def override_date(sub_id: uuid.UUID, body: ScheduleOverrideCreate, user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    sub = (await db.execute(select(Subscription).where(Subscription.id == sub_id, Subscription.customer_id == user.id))).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")

    # Centralized cutoff check
    assert_modifiable(body.date)

    # Upsert override
    existing = (await db.execute(
        select(SubscriptionScheduleOverride).where(
            SubscriptionScheduleOverride.subscription_id == sub_id,
            SubscriptionScheduleOverride.date == body.date,
        )
    )).scalar_one_or_none()
    if existing:
        existing.skip = body.skip
        existing.quantity_override = body.quantity_override
        existing.reason = body.reason
        ov = existing
    else:
        ov = SubscriptionScheduleOverride(
            subscription_id=sub_id, date=body.date, skip=body.skip,
            quantity_override=body.quantity_override, reason=body.reason,
        )
        db.add(ov)

    # If a DeliveryOrder for that date already exists AND is not yet locked, reflect immediately
    existing_order = (await db.execute(
        select(DeliveryOrder).where(
            DeliveryOrder.subscription_id == sub_id,
            DeliveryOrder.delivery_date == body.date,
        )
    )).scalar_one_or_none()
    if existing_order and existing_order.cutoff_locked_at is None:
        from app.models.enums import DeliveryOrderStatus
        if body.skip:
            existing_order.status = DeliveryOrderStatus.SKIPPED
            existing_order.skip_reason = body.reason or "customer override"
        elif body.quantity_override is not None:
            existing_order.quantity = body.quantity_override

    await db.flush()
    return ov


# delivery orders
@router.get("/me/delivery-orders", response_model=list[DeliveryOrderOut])
async def my_orders(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DeliveryOrder).where(DeliveryOrder.customer_id == user.id)
    if from_:
        stmt = stmt.where(DeliveryOrder.delivery_date >= from_)
    if to:
        stmt = stmt.where(DeliveryOrder.delivery_date <= to)
    stmt = stmt.order_by(DeliveryOrder.delivery_date.desc()).limit(500)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


# invoices
@router.get("/me/invoices", response_model=list[InvoiceOut])
async def my_invoices(user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Invoice).where(Invoice.customer_id == user.id).order_by(Invoice.year.desc(), Invoice.month.desc())
    )).scalars().all()
    return list(rows)


@router.get("/me/invoices/{invoice_id}", response_model=InvoiceDetailOut)
async def my_invoice_detail(invoice_id: uuid.UUID, user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    inv = (await db.execute(
        select(Invoice).options(selectinload(Invoice.line_items)).where(
            Invoice.id == invoice_id, Invoice.customer_id == user.id
        )
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")
    return inv


@router.get("/me/invoices/{invoice_id}/pdf")
async def my_invoice_pdf(
    invoice_id: uuid.UUID,
    download: bool = Query(False),
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    """Stream the invoice PDF (lazy-generated + cached via StorageProvider).

    Owner-only: non-owner requests return 404 (not 403) so we don't leak the
    existence of another customer's invoice.
    """
    from fastapi.responses import Response
    from app.services.invoice_pdf_service import get_or_generate

    inv = (await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.customer_id == user.id
        )
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")

    pdf = await get_or_generate(db, inv)
    disposition = "attachment" if download else "inline"
    filename = f"posuhtik_invoice_{inv.year}_{inv.month:02d}_{str(inv.id)[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


# wallet
@router.get("/me/wallet", response_model=WalletOut)
async def my_wallet(user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    txs = (await db.execute(
        select(WalletTransaction).where(WalletTransaction.customer_id == user.id)
        .order_by(WalletTransaction.created_at.desc()).limit(20)
    )).scalars().all()
    return WalletOut(
        customer_id=user.id,
        balance_paise=user.wallet_balance_paise,
        recent_transactions=[
            {"id": str(t.id), "change_paise": t.change_paise, "reason": t.reason,
             "balance_after_paise": t.balance_after_paise, "created_at": t.created_at.isoformat()}
            for t in txs
        ],
    )


# bottle balance
@router.get("/me/bottle-balance", response_model=BottleBalanceOut)
async def my_bottle(user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)):
    bal = await bottle_service.bottle_balance(db, user.id)
    return BottleBalanceOut(customer_id=user.id, balance=bal)
