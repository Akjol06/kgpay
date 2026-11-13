"""Minimal FastAPI shop taking Finik payments.

    pip install kgpay fastapi uvicorn
    FINIK_API_KEY=... FINIK_ACCOUNT_ID=... FINIK_PRIVATE_KEY=... uvicorn fastapi_app:app

In-memory "orders" stand in for your database.
"""

import os
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from kgpay import AsyncFinik, ForeignAccountError, InvalidSignatureError

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://shop.kg")
WEBHOOK_PATH = "/api/webhooks/finik"

finik = AsyncFinik(
    api_key=os.environ["FINIK_API_KEY"],
    account_id=os.environ["FINIK_ACCOUNT_ID"],
    private_key=os.environ["FINIK_PRIVATE_KEY"],
    sandbox=os.environ.get("FINIK_SANDBOX", "true") == "true",
    merchant_name="My Shop",
)

app = FastAPI()
orders: dict[str, dict] = {}


@app.post("/api/checkout")
async def checkout(total: int):
    order_id = str(uuid.uuid4())
    orders[order_id] = {"total": total, "paid": False}
    payment = await finik.create_payment(
        amount=total,
        payment_id=order_id,
        description=f"Заказ {order_id[:8]}",
        redirect_url=f"{PUBLIC_URL}/thanks?order={order_id}",
        webhook_url=f"{PUBLIC_URL}{WEBHOOK_PATH}",
    )
    return RedirectResponse(payment.url, status_code=303)


@app.post(WEBHOOK_PATH)
async def finik_webhook(request: Request):
    try:
        event = finik.parse_webhook(body=await request.body(), headers=request.headers, path=WEBHOOK_PATH)
    except InvalidSignatureError:
        raise HTTPException(status_code=401, detail="bad signature") from None
    except ForeignAccountError:
        return {"ok": True}  # signed by Finik, but paid to someone else: grant nothing

    order = orders.get(event.payment_id or "")
    # Idempotent: Finik retries, so a second delivery must change nothing.
    if event.succeeded and order and not order["paid"] and event.amount_covers(order["total"]):
        order["paid"] = True
    return {"ok": True}
