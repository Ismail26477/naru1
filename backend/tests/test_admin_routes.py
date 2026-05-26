"""Phase 2B.3 — routes list, detail, drag-drop reorder, add/remove stops."""
from __future__ import annotations
import pytest
import pytest_asyncio
import uuid as uuidm
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.enums import UserRole, DeliveryOrderStatus
from app.models.route import Route, RouteStop
from app.models.delivery import DeliveryOrder
from app.models.audit_log import AuditLog
from app.core.time_utils import now_utc, tomorrow_ist
from tests.conftest import auth_headers


@pytest_asyncio.fixture(loop_scope="session")
async def delivery_boy(db: AsyncSession) -> User:
    u = User(phone="+919000055001", name="Arjun Wagh", role=UserRole.DELIVERY, is_active=True, approved_at=now_utc())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def five_customers(db: AsyncSession) -> list[User]:
    users: list[User] = []
    for i in range(5):
        u = User(
            phone=f"+9190700{i:05d}", name=f"Customer {chr(ord('A') + i)}",
            role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc(),
        )
        db.add(u)
        users.append(u)
    await db.commit()
    for u in users:
        await db.refresh(u)
    return users


@pytest_asyncio.fixture(loop_scope="session")
async def seeded_route(db: AsyncSession, delivery_boy: User, five_customers: list[User]) -> Route:
    r = Route(name="Dharampeth Route", area="Dharampeth", delivery_boy_id=delivery_boy.id, active=True)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    for i, c in enumerate(five_customers, start=1):
        db.add(RouteStop(route_id=r.id, customer_id=c.id, sequence=i))
    await db.commit()
    return r


# ------------------- list + create -------------------

@pytest.mark.asyncio
async def test_route_list_pagination(client, admin_user, seeded_route):
    r = await client.get("/api/admin/routes", headers=auth_headers(admin_user))
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    row = next(x for x in d["items"] if x["id"] == str(seeded_route.id))
    assert row["stops_count"] == 5
    assert row["delivery_boy_name"] == "Arjun Wagh"


@pytest.mark.asyncio
async def test_route_list_filter_by_boy(client, admin_user, seeded_route, delivery_boy):
    r = await client.get(
        f"/api/admin/routes?delivery_boy_id={delivery_boy.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["items"]]
    assert str(seeded_route.id) in ids


@pytest.mark.asyncio
async def test_route_create_audit(client, admin_user, delivery_boy, db):
    r = await client.post(
        "/api/admin/routes",
        headers=auth_headers(admin_user),
        json={"name": "New Test Route", "area": "Sitabuldi", "delivery_boy_id": str(delivery_boy.id)},
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.entity_type == "route", AuditLog.entity_id == rid)
    )).scalars().all()
    actions = [row.action for row in rows]
    assert "route.create" in actions


# ------------------- reorder -------------------

@pytest.mark.asyncio
async def test_stops_reorder_single_move(client, admin_user, seeded_route, five_customers, db):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    stops = detail["stops"]
    # move last to first
    new_seq = [
        {"stop_id": stops[-1]["id"], "sequence": 1},
        {"stop_id": stops[0]["id"], "sequence": 2},
        {"stop_id": stops[1]["id"], "sequence": 3},
        {"stop_id": stops[2]["id"], "sequence": 4},
        {"stop_id": stops[3]["id"], "sequence": 5},
    ]
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json={"sequence": new_seq},
    )
    assert r.status_code == 200, r.text
    after = r.json()["stops"]
    assert after[0]["id"] == stops[-1]["id"]
    # DB-level verification: all positions consistent & contiguous
    persisted = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == seeded_route.id).order_by(RouteStop.sequence)
    )).scalars().all()
    assert [s.sequence for s in persisted] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_stops_reorder_multiple_moves(client, admin_user, seeded_route):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    ids = [s["id"] for s in detail["stops"]]
    reverse = [{"stop_id": ids[-i], "sequence": i} for i in range(1, 6)]
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json={"sequence": reverse},
    )
    assert r.status_code == 200
    after_ids = [s["id"] for s in r.json()["stops"]]
    assert after_ids == list(reversed(ids))


@pytest.mark.asyncio
async def test_stops_reorder_audit_shape(client, admin_user, seeded_route, db):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    ids = [s["id"] for s in detail["stops"]]
    payload = {"sequence": [{"stop_id": ids[i], "sequence": i + 1} for i in range(5)]}
    await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json=payload,
    )
    rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "route",
            AuditLog.entity_id == str(seeded_route.id),
            AuditLog.action == "route.reorder",
        )
        .order_by(AuditLog.created_at.desc())
    )).scalars().all()
    assert rows, "audit row expected"
    latest = rows[0]
    assert isinstance(latest.before_state, dict)
    assert isinstance(latest.after_state, dict)
    assert "stops" in latest.before_state and "stops" in latest.after_state
    assert all("stop_id" in s and "sequence" in s for s in latest.before_state["stops"])
    assert all("stop_id" in s and "sequence" in s for s in latest.after_state["stops"])


@pytest.mark.asyncio
async def test_stops_reorder_duplicate_sequence(client, admin_user, seeded_route):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    ids = [s["id"] for s in detail["stops"]]
    body = {"sequence": [
        {"stop_id": ids[0], "sequence": 1},
        {"stop_id": ids[1], "sequence": 1},  # duplicate
        {"stop_id": ids[2], "sequence": 3},
        {"stop_id": ids[3], "sequence": 4},
        {"stop_id": ids[4], "sequence": 5},
    ]}
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json=body,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "duplicate_sequence"


@pytest.mark.asyncio
async def test_stops_reorder_non_contiguous(client, admin_user, seeded_route):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    ids = [s["id"] for s in detail["stops"]]
    body = {"sequence": [
        {"stop_id": ids[0], "sequence": 1},
        {"stop_id": ids[1], "sequence": 2},
        {"stop_id": ids[2], "sequence": 4},  # gap
        {"stop_id": ids[3], "sequence": 5},
        {"stop_id": ids[4], "sequence": 6},
    ]}
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json=body,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "non_contiguous"


@pytest.mark.asyncio
async def test_stops_reorder_foreign_stop(client, admin_user, seeded_route):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    ids = [s["id"] for s in detail["stops"]]
    fake = str(uuidm.uuid4())
    body = {"sequence": [
        {"stop_id": fake, "sequence": 1},
        {"stop_id": ids[1], "sequence": 2},
        {"stop_id": ids[2], "sequence": 3},
        {"stop_id": ids[3], "sequence": 4},
        {"stop_id": ids[4], "sequence": 5},
    ]}
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json=body,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "foreign_or_missing_stop"


# ------------------- add / remove -------------------

@pytest.mark.asyncio
async def test_add_customer_already_on_route(client, admin_user, seeded_route, five_customers):
    r = await client.post(
        f"/api/admin/routes/{seeded_route.id}/stops",
        headers=auth_headers(admin_user),
        json={"customer_id": str(five_customers[0].id)},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_on_this_route"


@pytest.mark.asyncio
async def test_add_customer_on_other_route(client, admin_user, seeded_route, five_customers, delivery_boy, db):
    # Create a second route and try to add a customer who is already on seeded_route
    r2 = Route(name="Other Route", area="X", delivery_boy_id=delivery_boy.id, active=True)
    db.add(r2)
    await db.commit()
    await db.refresh(r2)
    r = await client.post(
        f"/api/admin/routes/{r2.id}/stops",
        headers=auth_headers(admin_user),
        json={"customer_id": str(five_customers[0].id)},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "on_other_route"


@pytest.mark.asyncio
async def test_remove_customer_resequences(client, admin_user, seeded_route, db):
    detail = (await client.get(
        f"/api/admin/routes/{seeded_route.id}", headers=auth_headers(admin_user)
    )).json()
    middle = detail["stops"][2]
    r = await client.delete(
        f"/api/admin/routes/{seeded_route.id}/stops/{middle['id']}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    persisted = (await db.execute(
        select(RouteStop).where(RouteStop.route_id == seeded_route.id).order_by(RouteStop.sequence)
    )).scalars().all()
    assert [s.sequence for s in persisted] == [1, 2, 3, 4]


# ------------------- deactivate -------------------

@pytest.mark.asyncio
async def test_deactivate_route_with_pending_deliveries(
    client, admin_user, seeded_route, five_customers, milk_product, db,
):
    # Seed a subscription + pending delivery for tomorrow on one of the route's customers
    from app.models.subscription import Subscription
    from app.models.enums import SubscriptionFrequency, SubscriptionStatus
    from datetime import date as _date
    sub = Subscription(
        customer_id=five_customers[0].id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=_date.today(),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    o = DeliveryOrder(
        customer_id=five_customers[0].id,
        subscription_id=sub.id,
        product_id=milk_product.id,
        delivery_date=tomorrow_ist(),
        quantity=1,
        unit_price_paise=milk_product.price_paise,
        status=DeliveryOrderStatus.PENDING,
    )
    db.add(o)
    await db.commit()

    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/deactivate",
        headers=auth_headers(admin_user),
        json={"reason": "End-of-operations cleanup cycle test"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "has_pending_deliveries"
    assert len(r.json()["detail"]["blocking_orders"]) >= 1


@pytest.mark.asyncio
async def test_deactivate_route_clean(client, admin_user, seeded_route):
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}/deactivate",
        headers=auth_headers(admin_user),
        json={"reason": "Retiring old route per ops lead"},
    )
    assert r.status_code == 200
    assert r.json()["active"] is False


# ------------------- RBAC -------------------

ENDPOINTS = [
    ("GET", "/api/admin/routes"),
    ("POST", "/api/admin/routes"),
    ("GET", "/api/admin/routes/{RID}"),
    ("PATCH", "/api/admin/routes/{RID}"),
    ("PATCH", "/api/admin/routes/{RID}/stops"),
    ("PATCH", "/api/admin/routes/{RID}/deactivate"),
    ("POST", "/api/admin/routes/{RID}/stops"),
]


@pytest.mark.asyncio
async def test_rbac_routes_customer_forbidden(client, customer_user, seeded_route):
    payload = {"name": "x", "area": "x", "sequence": [], "customer_id": str(uuidm.uuid4()),
               "reason": "Attempting unauthorised access scan test"}
    for method, path in ENDPOINTS:
        url = path.replace("{RID}", str(seeded_route.id))
        if method == "GET":
            r = await client.get(url, headers=auth_headers(customer_user))
        elif method == "POST":
            r = await client.post(url, headers=auth_headers(customer_user), json=payload)
        else:
            r = await client.patch(url, headers=auth_headers(customer_user), json=payload)
        assert r.status_code == 403, f"{method} {url} → {r.status_code}"


@pytest.mark.asyncio
async def test_rbac_routes_delivery_forbidden(client, delivery_user, seeded_route):
    payload = {"name": "x", "area": "x", "sequence": [], "customer_id": str(uuidm.uuid4()),
               "reason": "Attempting unauthorised access scan test"}
    for method, path in ENDPOINTS:
        url = path.replace("{RID}", str(seeded_route.id))
        if method == "GET":
            r = await client.get(url, headers=auth_headers(delivery_user))
        elif method == "POST":
            r = await client.post(url, headers=auth_headers(delivery_user), json=payload)
        else:
            r = await client.patch(url, headers=auth_headers(delivery_user), json=payload)
        assert r.status_code == 403, f"{method} {url} → {r.status_code}"


# ------------------- reassign delivery boy -------------------

@pytest.mark.asyncio
async def test_route_reassign_delivery_boy_audit(client, admin_user, seeded_route, db):
    # Create a second delivery boy and reassign
    new_boy = User(phone="+919000055002", name="Ravi Patil", role=UserRole.DELIVERY, is_active=True, approved_at=now_utc())
    db.add(new_boy)
    await db.commit()
    await db.refresh(new_boy)
    r = await client.patch(
        f"/api/admin/routes/{seeded_route.id}",
        headers=auth_headers(admin_user),
        json={"delivery_boy_id": str(new_boy.id)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["delivery_boy_id"] == str(new_boy.id)

    rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.action == "route.update",
            AuditLog.entity_id == str(seeded_route.id),
        ).order_by(AuditLog.created_at.desc())
    )).scalars().all()
    assert rows
    latest = rows[0]
    assert latest.before_state["delivery_boy_id"] != latest.after_state["delivery_boy_id"]
    assert latest.after_state["delivery_boy_id"] == str(new_boy.id)
