"""Seed dev database with Nagpur-specific data.

Usage:   python -m scripts.seed
         ./scripts/seed.py    (from /app/backend)
Idempotent: safe to re-run. Existing data is reused; subscriptions/delivery history
are regenerated only if not present for seeded customers.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timedelta, timezone
import uuid
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import select, delete
from app.db.session import AsyncSessionLocal
from app.models.user import User, Address
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.route import Route, RouteStop
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.billing import Invoice
from app.models.enums import (
    UserRole, ProductUnit, SubscriptionFrequency, SubscriptionStatus,
    DeliveryOrderStatus, BottleReason,
)
from app.core.time_utils import now_utc

ADMIN_PHONE = "+919000000001"
DB1_PHONE = "+919000000002"
DB2_PHONE = "+919000000003"

CUSTOMERS = [
    ("+919000000004", "Amit Kulkarni",    "Dharampeth",      "440010"),
    ("+919000000005", "Priya Sharma",     "Dharampeth",      "440010"),
    ("+919000000006", "Rahul Joshi",      "Ramdaspeth",      "440010"),
    ("+919000000007", "Sneha Deshpande",  "Civil Lines",     "440001"),
    ("+919000000008", "Vikram Bhoyar",    "Civil Lines",     "440001"),
    ("+919000000009", "Anjali Tiwari",    "Sadar",           "440001"),
    ("+919000000010", "Manish Agrawal",   "Sadar",           "440001"),
    ("+919000000011", "Kavita Meshram",   "Wardhaman Nagar", "440008"),
    ("+919000000012", "Deepak Raut",      "Pratap Nagar",    "440022"),
    ("+919000000013", "Swati Wankhede",   "Bajaj Nagar",     "440010"),
]

PRODUCTS = [
    ("Cow Milk 500ml",       "COW-MILK-500",  ProductUnit.LITRE, 3500, True),
    ("Cow Milk 1L",          "COW-MILK-1L",   ProductUnit.LITRE, 7000, True),
    ("A2 Bilona Ghee 500ml", "GHEE-500",      ProductUnit.KG,    120000, False),
    ("A2 Bilona Ghee 1L",    "GHEE-1L",       ProductUnit.KG,    230000, False),
    ("Fresh Paneer 250g",    "PANEER-250",    ProductUnit.KG,    11000, False),
    ("Buttermilk 500ml",     "BUTTER-500",    ProductUnit.LITRE, 2500, True),
]

ROUTE1_AREAS = {"Dharampeth", "Ramdaspeth", "Civil Lines"}
ROUTE2_AREAS = {"Sadar", "Wardhaman Nagar", "Pratap Nagar", "Bajaj Nagar"}


async def upsert_user(db, phone: str, name: str, role: UserRole, approved: bool = True) -> User:
    u = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if u:
        return u
    u = User(
        phone=phone, name=name, role=role, is_active=True,
        approved_at=now_utc() if approved else None,
    )
    db.add(u)
    await db.flush()
    return u


async def upsert_product(db, name, sku, unit, price_paise, requires_bottle):
    p = (await db.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()
    if p:
        return p
    p = Product(name=name, sku=sku, unit=unit, price_paise=price_paise, requires_bottle=requires_bottle, active=True)
    db.add(p)
    await db.flush()
    return p


async def seed():
    async with AsyncSessionLocal() as db:
        # Admin + delivery boys
        admin = await upsert_user(db, ADMIN_PHONE, "Admin User", UserRole.ADMIN)
        dboy1 = await upsert_user(db, DB1_PHONE, "Ramesh Patil", UserRole.DELIVERY)
        dboy2 = await upsert_user(db, DB2_PHONE, "Suresh Deshmukh", UserRole.DELIVERY)

        # Products
        products: list[Product] = []
        for p in PRODUCTS:
            products.append(await upsert_product(db, *p))
        milk500, milk1l, ghee500, ghee1l, paneer, buttermilk = products

        # Customers + addresses
        customers: list[User] = []
        for phone, name, area, pincode in CUSTOMERS:
            cust = await upsert_user(db, phone, name, UserRole.CUSTOMER)
            customers.append(cust)
            existing_addr = (await db.execute(select(Address).where(Address.user_id == cust.id))).scalar_one_or_none()
            if existing_addr:
                continue
            db.add(Address(
                user_id=cust.id, line1=f"Flat {20 + len(customers)}, Sunrise Apt",
                area=area, city="Nagpur", pincode=pincode,
                lat=21.1458, lng=79.0882, is_default=True, geocoding_pending=True,
            ))
        await db.flush()

        # Routes
        route1 = (await db.execute(select(Route).where(Route.name == "Dharampeth Morning"))).scalar_one_or_none()
        if not route1:
            route1 = Route(name="Dharampeth Morning", delivery_boy_id=dboy1.id, area="Dharampeth/Ramdaspeth/Civil Lines")
            db.add(route1)
            await db.flush()
        route2 = (await db.execute(select(Route).where(Route.name == "Sadar East"))).scalar_one_or_none()
        if not route2:
            route2 = Route(name="Sadar East", delivery_boy_id=dboy2.id, area="Sadar/Wardhaman/Pratap/Bajaj")
            db.add(route2)
            await db.flush()

        # Stops (assign each customer to exactly one route based on area)
        existing_stops = (await db.execute(select(RouteStop))).scalars().all()
        stopped_cust = {s.customer_id for s in existing_stops}
        seq_r1, seq_r2 = 1, 1
        for cust, (_, _, area, _) in zip(customers, CUSTOMERS):
            if cust.id in stopped_cust:
                continue
            if area in ROUTE1_AREAS:
                db.add(RouteStop(route_id=route1.id, customer_id=cust.id, sequence=seq_r1))
                seq_r1 += 1
            else:
                db.add(RouteStop(route_id=route2.id, customer_id=cust.id, sequence=seq_r2))
                seq_r2 += 1
        await db.flush()

        # Subscriptions — mix of frequencies + products
        start = (datetime.now(timezone.utc).date() - timedelta(days=20))

        # plan: each customer gets ~1 milk subscription, some get ghee/paneer/buttermilk too
        plan = [
            # customer_idx, product, quantity, freq, custom_days
            (0, milk500,     2, SubscriptionFrequency.DAILY,     None),
            (0, ghee500,     1, SubscriptionFrequency.WEEKLY,    "0"),        # every Monday
            (1, milk1l,      1, SubscriptionFrequency.DAILY,     None),
            (1, paneer,      1, SubscriptionFrequency.WEEKLY,    "5"),        # Saturdays
            (2, milk500,     1, SubscriptionFrequency.ALTERNATE, None),
            (3, milk1l,      2, SubscriptionFrequency.DAILY,     None),
            (3, buttermilk,  2, SubscriptionFrequency.CUSTOM,    "1,3,5"),
            (4, milk500,     3, SubscriptionFrequency.DAILY,     None),
            (5, milk1l,      1, SubscriptionFrequency.DAILY,     None),
            (5, ghee1l,      1, SubscriptionFrequency.CUSTOM,    "0"),
            (6, milk500,     2, SubscriptionFrequency.ALTERNATE, None),
            (7, milk1l,      1, SubscriptionFrequency.DAILY,     None),
            (8, milk500,     1, SubscriptionFrequency.WEEKLY,    "0,2,4"),
            (9, milk1l,      2, SubscriptionFrequency.DAILY,     None),
        ]
        for cust_idx, prod, qty, freq, days in plan:
            cust = customers[cust_idx]
            exists = (await db.execute(
                select(Subscription).where(
                    Subscription.customer_id == cust.id,
                    Subscription.product_id == prod.id,
                )
            )).scalar_one_or_none()
            if exists:
                continue
            db.add(Subscription(
                customer_id=cust.id, product_id=prod.id, quantity=qty,
                frequency=freq, custom_days=days, start_date=start, status=SubscriptionStatus.ACTIVE,
            ))
        await db.flush()

        # Past delivery history (for last 30 days) — so there's data to display
        from app.services.order_service import generate_orders_for_date
        today = datetime.now(timezone.utc).date()
        # Push start_date earlier if needed so the 30-day backfill covers every day
        for s in (await db.execute(select(Subscription))).scalars().all():
            earliest_needed = today - timedelta(days=30)
            if s.start_date > earliest_needed:
                s.start_date = earliest_needed
        await db.flush()
        for offset in range(30, 0, -1):
            d = today - timedelta(days=offset)
            created = await generate_orders_for_date(db, d)
            # Mark all as delivered with full quantity (some 10% random skipped)
            for o in created:
                prod = next((p for p in products if p.id == o.product_id), None)
                # Deterministic skip pattern: ~12% skips (every ~8th order)
                if (hash((str(o.id), offset)) % 8) == 0:
                    o.status = DeliveryOrderStatus.SKIPPED
                    o.skip_reason = "seed-skip"
                    o.delivered_at = now_utc()
                    continue
                o.status = DeliveryOrderStatus.DELIVERED
                o.delivered_quantity = o.quantity
                o.delivered_at = now_utc()
                if prod and prod.requires_bottle:
                    db.add(BottleLedger(
                        customer_id=o.customer_id, delivery_order_id=o.id,
                        change=o.quantity, reason=BottleReason.DELIVERED,
                        note=f"seed delivery {d}",
                    ))
                    # simulate returning previous day's bottles (partial)
                    if offset != 15:
                        db.add(BottleLedger(
                            customer_id=o.customer_id, delivery_order_id=o.id,
                            change=-o.quantity, reason=BottleReason.RETURNED,
                            note=f"seed return {d}",
                        ))
        await db.commit()

        # --- Phase 2C seed addition: generate last-month invoices, then simulate ---
        # --- a post-billing override so there's at least one invoice with        ---
        # --- has_post_billing_adjustments=true for the admin console callout.     ---
        try:
            from app.services import billing_admin_service as bas

            # System user seeded by migration e5c1b7f2a3d8
            sys_user = (await db.execute(
                select(User).where(User.is_system.is_(True))
            )).scalar_one_or_none()
            admin_user = (await db.execute(
                select(User).where(User.phone == ADMIN_PHONE)
            )).scalar_one()
            actor = sys_user or admin_user

            last_month_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            prev_y, prev_m = last_month_first.year, last_month_first.month

            # Generate invoices for previous month if none exist yet
            existing = (await db.execute(
                select(Invoice).where(Invoice.year == prev_y, Invoice.month == prev_m)
            )).scalars().all()
            if not existing:
                try:
                    await bas.generate_invoices(
                        db, year=prev_y, month=prev_m,
                        actor=actor, regenerate=False, reason=None,
                    )
                    await db.commit()
                except Exception as gen_err:  # noqa: BLE001 — seed must never crash
                    print(f"  (seed) billing_generate skipped: {gen_err}")

            # Pick the first invoice for (prev_y, prev_m) and apply a synthetic
            # post-billing override so the Phase-C callout has something to render.
            inv = (await db.execute(
                select(Invoice).where(
                    Invoice.year == prev_y, Invoice.month == prev_m,
                ).limit(1)
            )).scalar_one_or_none()
            if inv and not inv.has_post_billing_adjustments:
                # Any delivered order inside the period works as the reference.
                any_do = (await db.execute(
                    select(DeliveryOrder).where(
                        DeliveryOrder.customer_id == inv.customer_id,
                        DeliveryOrder.delivery_date >= date(prev_y, prev_m, 1),
                        DeliveryOrder.delivery_date <  today.replace(day=1),
                        DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
                    ).limit(1)
                )).scalar_one_or_none()
                await bas.flag_post_billing_adjustment(
                    db,
                    customer_id=inv.customer_id,
                    delivery_date=(any_do.delivery_date if any_do else date(prev_y, prev_m, 1)),
                    ledger_delta_paise=-3500,
                    reason="Seed demo: simulated post-billing skip override",
                    actor=actor,
                    reference_id=str(any_do.id) if any_do else None,
                )
                await db.commit()
                print(f"  seeded post-billing invoice {str(inv.id)[:8]} for {prev_y}-{prev_m:02d}")
        except Exception as seed_extra_err:  # noqa: BLE001
            print(f"  (seed) Phase 2C invoice seeding skipped: {seed_extra_err}")

        print("SEED OK")
        print(f"  admin: {ADMIN_PHONE}")
        print(f"  delivery boys: {DB1_PHONE}, {DB2_PHONE}")
        print(f"  customers: {len(customers)}")
        print(f"  products: {len(products)}")
        print(f"  OTP (dev): 123456 (fixed)")


if __name__ == "__main__":
    asyncio.run(seed())
