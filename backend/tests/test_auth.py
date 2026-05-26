"""Auth flow: request-otp → verify-otp → access protected route."""
import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_request_otp_returns_dev_code(client):
    r = await client.post("/api/auth/request-otp", json={"phone": "+919000000099"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["otp"] is not None  # dev mode returns OTP
    assert body["expires_in_seconds"] > 0


@pytest.mark.asyncio
async def test_dev_fixed_otp_works(client):
    # Request triggers user creation pipeline
    await client.post("/api/auth/request-otp", json={"phone": "+919888888888"})
    r = await client.post("/api/auth/verify-otp", json={"phone": "+919888888888", "otp": "123456"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["role"] == "customer"


@pytest.mark.asyncio
async def test_wrong_otp_rejected(client):
    await client.post("/api/auth/request-otp", json={"phone": "+919888888777"})
    r = await client.post("/api/auth/verify-otp", json={"phone": "+919888888777", "otp": "000000"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    r = await client.get("/api/me")
    assert r.status_code == 401 or r.status_code == 403


@pytest.mark.asyncio
async def test_me_with_token(client, admin_user):
    r = await client.get("/api/me", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert r.json()["phone"] == admin_user.phone


@pytest.mark.asyncio
async def test_refresh_token_flow(client):
    await client.post("/api/auth/request-otp", json={"phone": "+919777777777"})
    verify = await client.post("/api/auth/verify-otp", json={"phone": "+919777777777", "otp": "123456"})
    refresh = verify.json()["refresh_token"]
    r = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert r.json()["access_token"]
