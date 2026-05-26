"""Phase 2B.1 admin dashboard: RBAC + basic shape check."""
import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_customer_cannot_access_dashboard_stats(client, customer_user):
    r = await client.get("/api/admin/dashboard/stats", headers=auth_headers(customer_user))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delivery_cannot_access_dashboard_stats(client, delivery_user):
    r = await client.get("/api/admin/dashboard/stats", headers=auth_headers(delivery_user))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_dashboard_stats(client, admin_user):
    r = await client.get("/api/admin/dashboard/stats", headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()
    # Required keys present and trends have expected lengths
    for k in (
        "today_deliveries", "mtd_revenue_paise", "new_customers_mtd",
        "pending_approvals", "bottles_outstanding", "overdue_invoices",
        "active_subscriptions", "deliveries_trend_14d",
        "revenue_trend_30d", "signups_trend_30d", "generated_at",
    ):
        assert k in data, f"missing key {k}"
    assert len(data["deliveries_trend_14d"]) == 14
    assert len(data["revenue_trend_30d"]) == 30
    assert len(data["signups_trend_30d"]) == 30
    assert isinstance(data["today_deliveries"], int)


@pytest.mark.asyncio
async def test_no_token_rejected(client):
    r = await client.get("/api/admin/dashboard/stats")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_can_read_empty_audit_log(client, admin_user):
    r = await client.get("/api/admin/audit-log", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_customer_cannot_read_audit_log(client, customer_user):
    r = await client.get("/api/admin/audit-log", headers=auth_headers(customer_user))
    assert r.status_code == 403
