"""Tests for hardening fixes: CORS whitelist, OTP rate limit, token revocation."""
import pytest
from tests.conftest import auth_headers


# ---- OTP rate limiting (H2) ----
@pytest.mark.asyncio
async def test_otp_rate_limit_phone(client):
    phone = "+919555555001"
    # 5 requests succeed
    for i in range(5):
        r = await client.post("/api/auth/request-otp", json={"phone": phone})
        assert r.status_code == 200, f"iter {i}: {r.text}"
    # 6th returns 429
    r = await client.post("/api/auth/request-otp", json={"phone": phone})
    assert r.status_code == 429
    body = r.json()
    # FastAPI wraps dict detail under "detail"
    detail = body.get("detail") if isinstance(body, dict) else body
    assert detail.get("code") == "otp_rate_limit_phone"


@pytest.mark.asyncio
async def test_otp_different_phones_not_rate_limited(client):
    # Each phone has its own bucket
    for i in range(3):
        r = await client.post("/api/auth/request-otp", json={"phone": f"+91955556{i:04d}"})
        assert r.status_code == 200


# ---- Token revocation (H3) ----
@pytest.mark.asyncio
async def test_logout_revokes_token(client, customer_user):
    headers = auth_headers(customer_user)
    # works first
    r = await client.get("/api/me", headers=headers)
    assert r.status_code == 200
    # logout
    r = await client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200, r.text
    # same token now fails
    r = await client.get("/api/me", headers=headers)
    assert r.status_code == 401
    assert "revoked" in r.text.lower()


@pytest.mark.asyncio
async def test_admin_revoke_user_tokens(client, admin_user, customer_user):
    # Customer can call /me
    r = await client.get("/api/me", headers=auth_headers(customer_user))
    assert r.status_code == 200
    # Admin revokes
    r = await client.post(
        f"/api/admin/users/{customer_user.id}/revoke-tokens",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    # Customer token now fails (is_active=False check)
    r = await client.get("/api/me", headers=auth_headers(customer_user))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_only_admin_can_revoke_tokens(client, customer_user):
    # Customer cannot revoke any user
    r = await client.post(
        f"/api/admin/users/{customer_user.id}/revoke-tokens",
        headers=auth_headers(customer_user),
    )
    assert r.status_code == 403


# ---- CORS (H1) ----
@pytest.mark.asyncio
async def test_cors_disallowed_origin(client):
    """Unapproved origin must not receive access-control-allow-origin matching it."""
    r = await client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette returns 400 for disallowed CORS preflight or omits the ACAO header
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao != "https://evil.example.com"


@pytest.mark.asyncio
async def test_cors_allowed_origin(client):
    r = await client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
