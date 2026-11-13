"""Finik (finik.kg, AversPay acquiring): QR and card payments in KGS.

Docs: https://www.finik.kg/documentation/web-sdk/
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ._signing import canonical_string, sign, verify
from .errors import APIError, ForeignAccountError, InvalidPayloadError, InvalidSignatureError
from .models import Payment, PaymentStatus, WebhookEvent

PROD_HOST = "api.acquiring.averspay.kg"
SANDBOX_HOST = "beta.api.acquiring.averspay.kg"

# Finik's webhook-signing keys, as published in its docs (Справочник -> публичные ключи).
# Pass `public_key=` to override if Finik rotates them.
PROD_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuF/PUmhMPPidcMxhZBPb
BSGJoSphmCI+h6ru8fG8guAlcPMVlhs+ThTjw2LHABvciwtpj51ebJ4EqhlySPyT
hqSfXI6Jp5dPGJNDguxfocohaz98wvT+WAF86DEglZ8dEsfoumojFUy5sTOBdHEu
g94B4BbrJvjmBa1YIx9Azse4HFlWhzZoYPgyQpArhokeHOHIN2QFzJqeriANO+wV
aUMta2AhRVZHbfyJ36XPhGO6A5FYQWgjzkI65cxZs5LaNFmRx6pjnhjIeVKKgF99
4OoYCzhuR9QmWkPl7tL4Kd68qa/xHLz0Psnuhm0CStWOYUu3J7ZpzRK8GoEXRcr8
tQIDAQAB
-----END PUBLIC KEY-----"""

SANDBOX_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwlrlKz/8gLWd1ARWGA/8
o3a3Qy8G+hPifyqiPosiTY6nCHovANMIJXk6DH4qAqqZeLu8pLGxudkPbv8dSyG7
F9PZEAryMPzjoB/9P/F6g0W46K/FHDtwTM3YIVvstbEbL19m8yddv/xCT9JPPJTb
LsSTVZq5zCqvKzpupwlGS3Q3oPyLAYe+ZUn4Bx2J1WQrBu3b08fNaR3E8pAkCK27
JqFnP0eFfa817VCtyVKcFHb5ij/D0eUP519Qr/pgn+gsoG63W4pPHN/pKwQUUiAy
uLSHqL5S2yu1dffyMcMVi9E/Q2HCTcez5OvOllgOtkNYHSv9pnrMRuws3u87+hNT
ZwIDAQAB
-----END PUBLIC KEY-----"""

_SUCCESS = {"success", "succeeded"}
_FAILURE = {"failed", "failure", "declined", "canceled", "cancelled"}
_REDIRECTS = {301, 302, 303, 307, 308}
_PAYMENT_PATH = "/v1/payment"


def _whole_som(amount: int | Decimal | str) -> int:
    """Finik takes whole сом. Refuse fractions instead of silently rounding money."""
    if isinstance(amount, float):
        raise TypeError("Pass the amount as int or Decimal, not float")
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {amount!r}") from None
    if value <= 0 or value != value.to_integral_value():
        raise ValueError(f"Finik accepts a positive whole number of сом, got {amount!r}")
    return int(value)


class _FinikBase:
    def __init__(
        self,
        *,
        api_key: str,
        account_id: str,
        private_key: str | bytes,
        sandbox: bool = False,
        public_key: str | bytes | None = None,
        merchant_name: str | None = None,
        lang: str = "ru",
        timeout: float = 20.0,
    ) -> None:
        if not (api_key and account_id and private_key):
            raise ValueError("api_key, account_id and private_key are required")
        self.api_key = api_key
        self.account_id = str(account_id)
        self.private_key = private_key
        self.sandbox = sandbox
        self.public_key = public_key or (SANDBOX_PUBLIC_KEY if sandbox else PROD_PUBLIC_KEY)
        self.merchant_name = merchant_name
        self.lang = lang
        self.timeout = timeout

    @property
    def host(self) -> str:
        return SANDBOX_HOST if self.sandbox else PROD_HOST

    # --- creating a payment ---------------------------------------------------

    def _build_payment_request(
        self,
        *,
        amount: int | Decimal | str,
        payment_id: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        card_type: str,
    ) -> tuple[str, dict[str, str], bytes]:
        data: dict[str, Any] = {
            "accountId": self.account_id,
            "description": description,
            # Required: without it the payment result never reaches you.
            "webhookUrl": webhook_url,
        }
        if self.merchant_name:
            data["name_en"] = self.merchant_name  # shown on the payment page
        body = {
            "Amount": _whole_som(amount),
            "CardType": card_type,
            "PaymentId": payment_id,
            "RedirectUrl": redirect_url,
            "Lang": self.lang,
            "Data": data,
        }
        timestamp = str(int(time.time() * 1000))
        signed = {"Host": self.host, "x-api-key": self.api_key, "x-api-timestamp": timestamp}
        signature = sign(canonical_string("POST", _PAYMENT_PATH, signed, body), self.private_key)
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "x-api-timestamp": timestamp,
            "signature": signature,
        }
        # Serialised exactly as it was signed.
        return f"https://{self.host}{_PAYMENT_PATH}", headers, json.dumps(body, ensure_ascii=False).encode()

    @staticmethod
    def _parse_payment_response(resp: httpx.Response, payment_id: str) -> Payment:
        # Finik answers 302 with the payment page in Location; errors are JSON
        # {"StatusCode": 400, "ErrorMessage": "..."}.
        location = resp.headers.get("Location")
        if resp.status_code in _REDIRECTS and location:
            return Payment(payment_id=payment_id, url=location)
        if resp.status_code in (200, 201):
            try:
                url = (resp.json() or {}).get("paymentUrl")
            except ValueError:
                url = None
            if url:
                return Payment(payment_id=payment_id, url=url)
        message = f"Finik create_payment failed: HTTP {resp.status_code}"
        try:
            err = resp.json()
            if isinstance(err, dict) and err.get("ErrorMessage"):
                message += f": {err['ErrorMessage']}"
        except ValueError:
            pass
        raise APIError(message, status_code=resp.status_code, response_text=resp.text[:1000])

    # --- webhooks ---------------------------------------------------------------

    def parse_webhook(
        self,
        *,
        body: bytes | str | Mapping[str, Any],
        headers: Mapping[str, str],
        path: str,
        check_account: bool = True,
    ) -> WebhookEvent:
        """Verify a Finik webhook and return the payment result.

        `path` is the PUBLIC path Finik called (e.g. "/api/webhooks/finik"). Behind a
        proxy that strips a prefix, this differs from what your app sees, and the
        signature will not verify with the wrong one.

        Raises InvalidSignatureError for anything not signed by Finik and
        ForeignAccountError for a payment to another merchant's account.
        Finik retries unacknowledged webhooks for days, so make crediting
        idempotent (by payment_id) and answer 200 quickly.
        """
        if isinstance(body, (bytes, str)):
            try:
                data = json.loads(body or "{}")
            except ValueError:
                raise InvalidPayloadError("Webhook body is not valid JSON") from None
        else:
            data = dict(body)
        if not isinstance(data, dict):
            raise InvalidPayloadError("Webhook body must be a JSON object")

        headers = dict(headers)
        signature = next((v for k, v in headers.items() if k.lower() == "signature"), None)
        if not signature:
            raise InvalidSignatureError("Webhook has no signature header")
        try:
            canonical = canonical_string("POST", path, headers, data)
        except ValueError as exc:
            raise InvalidSignatureError(str(exc)) from None
        if not verify(canonical, signature, self.public_key):
            raise InvalidSignatureError("Webhook signature does not verify")

        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        extra = data.get("data") if isinstance(data.get("data"), dict) else {}
        account_id = str(extra["accountId"]) if extra.get("accountId") else None
        # One Finik key signs webhooks for ALL merchants: a valid signature means
        # "from Finik", not "paid to you". Without this check anyone with their own
        # Finik account could pay themselves using your payment_id and webhook URL.
        if check_account and account_id != self.account_id:
            raise ForeignAccountError(
                f"Webhook is for account {account_id!r}, not {self.account_id!r}", account_id=account_id
            )

        raw_status = str(data.get("status") or "").lower()
        if raw_status in _SUCCESS:
            status = PaymentStatus.SUCCEEDED
        elif raw_status in _FAILURE:
            status = PaymentStatus.FAILED
        else:
            status = PaymentStatus.UNKNOWN

        amount_raw = data.get("amount")
        try:
            amount = Decimal(str(amount_raw)) if amount_raw not in (None, "") else None
        except InvalidOperation:
            amount = None

        return WebhookEvent(
            status=status,
            payment_id=fields.get("paymentId") or data.get("paymentId"),
            transaction_id=data.get("transactionId"),
            amount=amount,
            account_id=account_id,
            raw=data,
        )


class Finik(_FinikBase):
    """Synchronous Finik client (Django, Flask, scripts)."""

    def __init__(self, *, http_client: httpx.Client | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._http = http_client

    def create_payment(
        self,
        *,
        amount: int | Decimal | str,
        payment_id: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        card_type: str = "FINIK_QR",
    ) -> Payment:
        """Create a payment and return the URL to send the customer to.

        `payment_id` is your own unique id (e.g. order id); it comes back in the webhook.
        """
        url, headers, content = self._build_payment_request(
            amount=amount,
            payment_id=payment_id,
            description=description,
            redirect_url=redirect_url,
            webhook_url=webhook_url,
            card_type=card_type,
        )
        try:
            if self._http is not None:
                resp = self._http.post(url, headers=headers, content=content, follow_redirects=False)
            else:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, headers=headers, content=content, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise APIError(f"Finik request failed: {exc}") from exc
        return self._parse_payment_response(resp, payment_id)


class AsyncFinik(_FinikBase):
    """Async Finik client (FastAPI, aiohttp)."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._http = http_client

    async def create_payment(
        self,
        *,
        amount: int | Decimal | str,
        payment_id: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        card_type: str = "FINIK_QR",
    ) -> Payment:
        """Create a payment and return the URL to send the customer to."""
        url, headers, content = self._build_payment_request(
            amount=amount,
            payment_id=payment_id,
            description=description,
            redirect_url=redirect_url,
            webhook_url=webhook_url,
            card_type=card_type,
        )
        try:
            if self._http is not None:
                resp = await self._http.post(url, headers=headers, content=content, follow_redirects=False)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, headers=headers, content=content, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise APIError(f"Finik request failed: {exc}") from exc
        return self._parse_payment_response(resp, payment_id)
