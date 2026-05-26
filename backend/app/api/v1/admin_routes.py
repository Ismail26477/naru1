"""Admin route management + drag-drop stop sequencing (Phase 2B.3).

Sequence invariants on PATCH /routes/{id}/stops:
- Every `stop_id` must belong to this route.
- `sequence` values form a contiguous 1..N permutation (no gaps, no dupes).
- Full replace happens in one transaction; before/after arrays captured in audit.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.user import User, Address
from app.models.enums import UserRole, DeliveryOrderStatus
from app.models.route import Route, RouteStop
from app.models.delivery import DeliveryOrder, BottleLedger
from app.schemas.admin import (
    RouteCreateBody, RouteUpdateBody, RouteStopSummary, RouteListRow,
    PaginatedRoutes, RouteDetail, ReorderStopsBody2, AddStopBody, ReasonBody,
)
from app.services import audit_service
from app.core.time_utils import tomorrow_ist

router = APIRouter(
    prefix="/admin",
    tags=["admin-routes"],
    dependencies=[Depends(require_admin)],
)


# ---------- helpers ----------

async def _get_route_or_404(db: AsyncSession, route_id: uuid.UUID) -> Route:
    r = (await db.execute(select(Route).where(Route.id == route_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="route not found")
    return r


async def _stop_summaries(db: AsyncSession, route_id: uuid.UUID) -> list[RouteStopSummary]:
    """Build enriched ordered stop list with customer + bottle balance."""
    stops = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)
    )).scalars().all()
    if not stops:
        return []
    cust_ids = [s.customer_id for s in stops]

    users = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_(cust_ids)))).scalars().all()
    }
    # default address per customer (fallback: first by created)
    addr_rows = (await db.execute(
        select(Address.user_id, Address.area, Address.lat, Address.lng, Address.is_default)
        .where(Address.user_id.in_(cust_ids))
        .order_by(Address.user_id, Address.is_default.desc(), Address.created_at.asc())
    )).all()
    addr_map: dict[uuid.UUID, dict] = {}
    for uid, area, lat, lng, _is_def in addr_rows:
        addr_map.setdefault(uid, {"area": area, "lat": lat, "lng": lng})

    bot_rows = (await db.execute(
        select(BottleLedger.customer_id, func.coalesce(func.sum(BottleLedger.change), 0))
        .where(BottleLedger.customer_id.in_(cust_ids))
        .group_by(BottleLedger.customer_id)
    )).all()
    bot_map = {r[0]: int(r[1]) for r in bot_rows}

    return [
        RouteStopSummary(
            id=s.id, sequence=s.sequence, customer_id=s.customer_id,
            customer_name=users[s.customer_id].name if s.customer_id in users else None,
            customer_phone=users[s.customer_id].phone if s.customer_id in users else "",
            customer_area=addr_map.get(s.customer_id, {}).get("area"),
            customer_lat=addr_map.get(s.customer_id, {}).get("lat"),
            customer_lng=addr_map.get(s.customer_id, {}).get("lng"),
            bottle_balance=bot_map.get(s.customer_id, 0),
        )
        for s in stops
    ]


def _route_detail_payload(route: Route, boy: User | None, stops: list[RouteStopSummary]) -> RouteDetail:
    return RouteDetail(
        id=route.id, name=route.name, area=route.area, active=route.active,
        delivery_boy_id=route.delivery_boy_id,
        delivery_boy_name=(boy.name if boy else None),
        delivery_boy_phone=(boy.phone if boy else None),
        stops=stops,
    )


# ---------- list ----------

@router.get("/routes", response_model=PaginatedRoutes)
async def list_routes_v2(
    delivery_boy_id: uuid.UUID | None = None,
    area: str | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    base = select(Route)
    if delivery_boy_id is not None:
        base = base.where(Route.delivery_boy_id == delivery_boy_id)
    if area:
        base = base.where(Route.area.ilike(f"%{area}%"))
    if active is not None:
        base = base.where(Route.active.is_(active))
    total = int((await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one() or 0)
    offset = (page - 1) * page_size
    routes = (await db.execute(
        base.order_by(Route.name).offset(offset).limit(page_size)
    )).scalars().all()
    if not routes:
        return PaginatedRoutes(items=[], total=total, page=page, page_size=page_size)

    ids = [r.id for r in routes]
    # stop counts
    sc_rows = (await db.execute(
        select(RouteStop.route_id, func.count(RouteStop.id))
        .where(RouteStop.route_id.in_(ids))
        .group_by(RouteStop.route_id)
    )).all()
    sc_map = {r[0]: int(r[1]) for r in sc_rows}

    # delivery boys
    boy_ids = [r.delivery_boy_id for r in routes if r.delivery_boy_id]
    boys = {
        u.id: u for u in
        (await db.execute(select(User).where(User.id.in_(boy_ids)))).scalars().all()
    } if boy_ids else {}

    # last delivery per route = latest delivery_orders.delivery_date among customers on route
    ld_map: dict[uuid.UUID, date] = {}
    if ids:
        ld_rows = (await db.execute(
            select(RouteStop.route_id, func.max(DeliveryOrder.delivery_date))
            .join(DeliveryOrder, DeliveryOrder.customer_id == RouteStop.customer_id)
            .where(RouteStop.route_id.in_(ids))
            .group_by(RouteStop.route_id)
        )).all()
        ld_map = {r[0]: r[1] for r in ld_rows}

    items = [
        RouteListRow(
            id=r.id, name=r.name, area=r.area, active=r.active,
            delivery_boy_id=r.delivery_boy_id,
            delivery_boy_name=(boys[r.delivery_boy_id].name if r.delivery_boy_id in boys else None),
            delivery_boy_phone=(boys[r.delivery_boy_id].phone if r.delivery_boy_id in boys else None),
            stops_count=sc_map.get(r.id, 0),
            last_delivery_date=ld_map.get(r.id),
        )
        for r in routes
    ]
    return PaginatedRoutes(items=items, total=total, page=page, page_size=page_size)


# ---------- create / update ----------

@router.post("/routes", response_model=RouteDetail, status_code=201)
async def create_route_v2(
    body: RouteCreateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.delivery_boy_id:
        boy = (await db.execute(
            select(User).where(User.id == body.delivery_boy_id, User.role == UserRole.DELIVERY)
        )).scalar_one_or_none()
        if not boy:
            raise HTTPException(status_code=400, detail="delivery_boy_id must reference a DELIVERY user")
    r = Route(name=body.name, area=body.area, delivery_boy_id=body.delivery_boy_id, active=True)
    db.add(r)
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="route.create",
        entity_type="route", entity_id=str(r.id),
        before_state=None,
        after_state={"name": r.name, "area": r.area, "delivery_boy_id": str(r.delivery_boy_id) if r.delivery_boy_id else None},
        request=request,
    )
    boy = None
    if r.delivery_boy_id:
        boy = (await db.execute(select(User).where(User.id == r.delivery_boy_id))).scalar_one_or_none()
    return _route_detail_payload(r, boy, [])


@router.get("/routes/{route_id}", response_model=RouteDetail)
async def route_detail(route_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await _get_route_or_404(db, route_id)
    boy = None
    if r.delivery_boy_id:
        boy = (await db.execute(select(User).where(User.id == r.delivery_boy_id))).scalar_one_or_none()
    stops = await _stop_summaries(db, r.id)
    return _route_detail_payload(r, boy, stops)


@router.patch("/routes/{route_id}", response_model=RouteDetail)
async def update_route(
    route_id: uuid.UUID,
    body: RouteUpdateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await _get_route_or_404(db, route_id)
    before = {
        "name": r.name, "area": r.area,
        "delivery_boy_id": str(r.delivery_boy_id) if r.delivery_boy_id else None,
        "active": r.active,
    }
    if body.delivery_boy_id is not None:
        boy = (await db.execute(
            select(User).where(User.id == body.delivery_boy_id, User.role == UserRole.DELIVERY)
        )).scalar_one_or_none()
        if not boy:
            raise HTTPException(status_code=400, detail="delivery_boy_id must reference a DELIVERY user")
        r.delivery_boy_id = body.delivery_boy_id
    if body.name is not None:
        r.name = body.name
    if body.area is not None:
        r.area = body.area
    if body.active is not None:
        r.active = body.active
    await db.flush()
    after = {
        "name": r.name, "area": r.area,
        "delivery_boy_id": str(r.delivery_boy_id) if r.delivery_boy_id else None,
        "active": r.active,
    }
    await audit_service.log_action(
        db, actor=admin, action="route.update",
        entity_type="route", entity_id=str(r.id),
        before_state=before, after_state=after, request=request,
    )
    boy = None
    if r.delivery_boy_id:
        boy = (await db.execute(select(User).where(User.id == r.delivery_boy_id))).scalar_one_or_none()
    stops = await _stop_summaries(db, r.id)
    return _route_detail_payload(r, boy, stops)


@router.patch("/routes/{route_id}/deactivate", response_model=RouteDetail)
async def deactivate_route(
    route_id: uuid.UUID,
    body: ReasonBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await _get_route_or_404(db, route_id)
    # Block if any PENDING deliveries for tomorrow among this route's customers
    td = tomorrow_ist()
    blocking = (await db.execute(
        select(DeliveryOrder.id, DeliveryOrder.customer_id, DeliveryOrder.delivery_date)
        .join(RouteStop, RouteStop.customer_id == DeliveryOrder.customer_id)
        .where(
            RouteStop.route_id == route_id,
            DeliveryOrder.delivery_date == td,
            DeliveryOrder.status == DeliveryOrderStatus.PENDING,
        )
    )).all()
    if blocking:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "has_pending_deliveries",
                "message": f"Route has {len(blocking)} pending delivery orders for tomorrow. Resolve them first.",
                "delivery_date": td.isoformat(),
                "blocking_orders": [
                    {"order_id": str(o[0]), "customer_id": str(o[1])} for o in blocking
                ],
            },
        )
    before = {"active": r.active}
    r.active = False
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="route.deactivate",
        entity_type="route", entity_id=str(r.id),
        before_state=before, after_state={"active": False},
        reason=body.reason, request=request,
    )
    return await route_detail(route_id, db)


# ---------- stops: reorder ----------

@router.patch("/routes/{route_id}/stops", response_model=RouteDetail)
async def reorder_stops_v2(
    route_id: uuid.UUID,
    body: ReorderStopsBody2,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_route_or_404(db, route_id)

    # Existing stops
    existing = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)
    )).scalars().all()
    existing_ids = {s.id for s in existing}

    # Validate: same set of stop_ids, contiguous 1..N, no dupes
    body_ids = [item.stop_id for item in body.sequence]
    if len(body.sequence) != len(existing):
        raise HTTPException(
            status_code=400,
            detail={"code": "stop_count_mismatch", "message": f"sequence has {len(body.sequence)} items but route has {len(existing)} stops"},
        )
    if set(body_ids) != existing_ids:
        raise HTTPException(
            status_code=400,
            detail={"code": "foreign_or_missing_stop", "message": "stop_ids must match exactly the stops of this route"},
        )
    seqs = [item.sequence for item in body.sequence]
    if len(set(seqs)) != len(seqs):
        raise HTTPException(status_code=400, detail={"code": "duplicate_sequence", "message": "sequence numbers must be unique"})
    if sorted(seqs) != list(range(1, len(seqs) + 1)):
        raise HTTPException(
            status_code=400,
            detail={"code": "non_contiguous", "message": f"sequence must be 1..{len(seqs)} with no gaps"},
        )

    before_state = [{"stop_id": str(s.id), "sequence": s.sequence} for s in existing]

    # Apply in a single transaction. The unique constraint is on (route_id, customer_id)
    # and customer_id globally; `sequence` has no unique constraint so a simple loop works.
    seq_map = {item.stop_id: item.sequence for item in body.sequence}
    for s in existing:
        s.sequence = seq_map[s.id]
    await db.flush()

    after_state = [
        {"stop_id": str(s.id), "sequence": s.sequence}
        for s in sorted(existing, key=lambda x: x.sequence)
    ]
    await audit_service.log_action(
        db, actor=admin, action="route.reorder",
        entity_type="route", entity_id=str(route_id),
        before_state={"stops": before_state},
        after_state={"stops": after_state},
        request=request,
    )

    return await route_detail(route_id, db)


# ---------- stops: add / remove ----------

@router.post("/routes/{route_id}/stops", response_model=RouteDetail, status_code=201)
async def add_stop(
    route_id: uuid.UUID,
    body: AddStopBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_route_or_404(db, route_id)

    cust = (await db.execute(
        select(User).where(User.id == body.customer_id, User.role == UserRole.CUSTOMER)
    )).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=404, detail="customer not found")

    # Already on this route?
    already = (await db.execute(
        select(RouteStop).where(
            RouteStop.route_id == route_id, RouteStop.customer_id == body.customer_id,
        )
    )).scalar_one_or_none()
    if already:
        raise HTTPException(status_code=409, detail={"code": "already_on_this_route", "message": "customer is already on this route"})
    # Already on another route?
    elsewhere = (await db.execute(
        select(RouteStop).where(
            RouteStop.customer_id == body.customer_id, RouteStop.route_id != route_id,
        )
    )).scalar_one_or_none()
    if elsewhere:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "on_other_route",
                "message": "customer is already assigned to a different route; remove there first",
                "other_route_id": str(elsewhere.route_id),
            },
        )

    existing = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)
    )).scalars().all()
    n = len(existing)
    target_pos = body.position if body.position is not None else n + 1
    if target_pos < 1 or target_pos > n + 1:
        raise HTTPException(status_code=400, detail={"code": "invalid_position", "message": f"position must be between 1 and {n + 1}"})

    # Shift: bump sequences of stops at >= target_pos
    for s in existing:
        if s.sequence >= target_pos:
            s.sequence = s.sequence + 1

    new_stop = RouteStop(route_id=route_id, customer_id=body.customer_id, sequence=target_pos)
    db.add(new_stop)
    await db.flush()

    await audit_service.log_action(
        db, actor=admin, action="route.assign_customer",
        entity_type="route", entity_id=str(route_id),
        before_state={"stops_count": n},
        after_state={
            "stops_count": n + 1,
            "added_stop_id": str(new_stop.id),
            "customer_id": str(body.customer_id),
            "position": target_pos,
        },
        request=request,
    )
    return await route_detail(route_id, db)


@router.delete("/routes/{route_id}/stops/{stop_id}", response_model=RouteDetail)
async def remove_stop(
    route_id: uuid.UUID,
    stop_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_route_or_404(db, route_id)
    stop = (await db.execute(
        select(RouteStop).where(RouteStop.id == stop_id, RouteStop.route_id == route_id)
    )).scalar_one_or_none()
    if not stop:
        raise HTTPException(status_code=404, detail="stop not found on this route")

    removed_seq = stop.sequence
    removed_cust = stop.customer_id
    await db.delete(stop)
    await db.flush()

    # Re-sequence remaining stops to stay 1..N contiguous
    remaining = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == route_id).order_by(RouteStop.sequence)
    )).scalars().all()
    for s in remaining:
        if s.sequence > removed_seq:
            s.sequence = s.sequence - 1
    await db.flush()

    await audit_service.log_action(
        db, actor=admin, action="route.remove_customer",
        entity_type="route", entity_id=str(route_id),
        before_state={"stops_count": len(remaining) + 1, "removed_sequence": removed_seq},
        after_state={
            "stops_count": len(remaining),
            "removed_stop_id": str(stop_id),
            "customer_id": str(removed_cust),
        },
        request=request,
    )
    return await route_detail(route_id, db)
