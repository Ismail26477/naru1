"""Razorpay webhook (stubbed in Phase 1, ready for wiring)."""
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.providers import get_payment_provider

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    provider = get_payment_provider()
    if not provider.verify_webhook_signature(raw, signature):
        raise HTTPException(status_code=400, detail="invalid signature")
    # Phase 1: log only. Real implementation will parse payment.captured and mark payments paid.
    import logging
    logging.getLogger("webhook.razorpay").info(f"razorpay webhook len={len(raw)}")
    return {"ok": True}
