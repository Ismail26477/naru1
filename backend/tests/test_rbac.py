"""RBAC: customer cannot access admin endpoints; delivery boy cannot either."""
import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_customer_cannot_list_customers(client, customer_user):
    r = await client.get("/api/admin/customers", headers=auth_headers(customer_user))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_approve(client, customer_user):
    r = await client.post(
        f"/api/admin/customers/{customer_user.id}/approve",
        headers=auth_headers(customer_user),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_generate_invoices(client, customer_user):
    r = await client.post(
        "/api/admin/invoices/generate?month=4&year=2025",
        headers=auth_headers(customer_user),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delivery_cannot_access_admin(client, delivery_user):
    r = await client.get("/api/admin/routes", headers=auth_headers(delivery_user))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_customer_cannot_use_delivery_endpoints(client, customer_user):
    r = await client.get("/api/delivery/my-route", headers=auth_headers(customer_user))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_customers(client, admin_user):
    r = await client.get("/api/admin/customers", headers=auth_headers(admin_user))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_no_token_is_unauthorized(client):
    r = await client.get("/api/admin/customers")
    assert r.status_code in (401, 403)
