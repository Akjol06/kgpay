"""FreedomPay (freedompay.kg, PayBox protocol): cards, wallets and QR.

Docs: https://freedompay.kg/docs-en/merchant-api/pay

Signature (PayBox): md5("<script>;<param values sorted by param name>;<secret_key>"),
where <script> is the last path segment of the URL being called:
"init_payment.php" for creating a payment, and the last segment of YOUR
result URL (e.g. "freedompay" for /api/webhooks/freedompay) for the callback
and for your reply to it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape

import httpx

from .errors import APIError, InvalidPayloadError, InvalidSignatureError
from .models import Payment, PaymentStatus, WebhookEvent

BASE_URL = "https://api.freedompay.kg"
INIT_SCRIPT = "init_payment.php"


def script_name(path: str) -> str:
    """The PayBox "script name" of a URL or path: its last non-empty segment."""
    path = path.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1]


def make_signature(script: str, params: Mapping[str, Any], secret_key: str) -> str:
    """md5(script ; values sorted by key ; secret). `pg_sig` itself is excluded."""
    values = [str(params[k]) for k in sorted(params) if k != "pg_sig"]
    return hashlib.md5(";".join([script, *values, secret_key]).encode("utf-8")).hexdigest()


def _amount(amount: int | Decimal | str) -> str:
    if isinstance(amount, float):
        raise TypeError("Pass the amount as int, Decimal or str, not float")
    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {amount!r}") from None
    if value < Decimal("0.01") or value != value.quantize(Decimal("0.01")):
        raise ValueError(f"Amount must be at least 0.01 with at most 2 decimals, got {amount!r}")
    return format(value.normalize(), "f")


class _FreedomPayBase:
    def __init__(
        self,
        *,
        merchant_id: str | int,
        secret_key: str,
        testing: bool = False,
        currency: str = "KGS",
        language: str = "ru",
        base_url: str = BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if not (merchant_id and secret_key):
            raise ValueError("merchant_id and secret_key are required")
        self.merchant_id = str(merchant_id)
        self.secret_key = secret_key
        self.testing = testing
        self.currency = currency
        self.language = language
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # --- creating a payment ---------------------------------------------------

    def _build_init(
        self,
        *,
        amount: int | Decimal | str,
        payment_id: str,
        description: str,
        redirect_url: str,
        webhook_url: str,
        failure_url: str | None,
        lifetime: int | None,
        extra: Mapping[str, Any] | None,
    ) -> tuple[str, dict[str, str]]:
        params: dict[str, str] = {
            "pg_merchant_id": self.merchant_id,
            "pg_order_id": str(payment_id),
            "pg_amount": _amount(amount),
            "pg_currency": self.currency,
            "pg_description": description,
            "pg_salt": secrets.token_hex(8),
            "pg_language": self.language,
            "pg_result_url": webhook_url,
            "pg_request_method": "POST",
            "pg_success_url": redirect_url,
            "pg_success_url_method": "GET",
            "pg_failure_url": failure_url or redirect_url,
            "pg_failure_url_method": "GET",
        }
        if lifetime is not None:
            params["pg_lifetime"] = str(int(lifetime))
        if self.testing:
            params["pg_testing_mode"] = "1"
        for key, value in (extra or {}).items():
            if isinstance(value, (dict, list, tuple)):
                raise TypeError(f"Nested values are not supported in extra (got {key!r})")
            params[key] = str(value)
        params["pg_sig"] = make_signature(INIT_SCRIPT, params, self.secret_key)
        return f"{self.base_url}/{INIT_SCRIPT}", params

    @staticmethod
    def _parse_init(resp: httpx.Response, payment_id: str) -> Payment:
        if resp.status_code != 200:
            raise APIError(
                f"FreedomPay init_payment failed: HTTP {resp.status_code}",
                status_code=resp.status_code,
                response_text=resp.text[:1000],
            )
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            raise APIError(
                "FreedomPay returned a non-XML response", status_code=200, response_text=resp.text[:1000]
            ) from None
        url = root.findtext("pg_redirect_url")
        if root.findtext("pg_status") != "ok" or not url:
            reason = root.findtext("pg_error_description") or root.findtext("pg_error_code") or "unknown error"
            raise APIError(
                f"FreedomPay rejected the payment: {reason}", status_code=200, response_text=resp.text[:1000]
            )
        return Payment(payment_id=payment_id, url=url, provider_payment_id=root.findtext("pg_payment_id"))

    # --- webhooks (result_url) ------------------------------------------------

    def parse_webhook(self, *, body: bytes | str | Mapping[str, Any], path: str) -> WebhookEvent:
        """Verify FreedomPay's result callback and return the payment result.

        `body` is the raw form-encoded request body (or an already parsed dict).
        `path` is the PUBLIC path of your result URL; its last segment is the
        script name FreedomPay signed with.
        """
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        if isinstance(body, str):
            params = dict(parse_qsl(body, keep_blank_values=True))
        elif isinstance(body, Mapping):
            params = {k: v for k, v in body.items()}
        else:
            raise InvalidPayloadError("Webhook body must be form data")
        if not params:
            raise InvalidPayloadError("Webhook body is empty")

        received = str(params.get("pg_sig") or "")
        expected = make_signature(script_name(path), params, self.secret_key)
        if not received or not hmac.compare_digest(received, expected):
            raise InvalidSignatureError("Webhook signature does not verify")
        if str(params.get("pg_testing_mode") or "0") == "1" and not self.testing:
            # Test payments move no money: never let one through in live mode.
            raise InvalidSignatureError("Test-mode payment received by a live client")

        result = str(params.get("pg_result") or "")
        status = {
            "1": PaymentStatus.SUCCEEDED,
            "0": PaymentStatus.FAILED,
            "2": PaymentStatus.PENDING,
        }.get(result, PaymentStatus.UNKNOWN)

        try:
            amount = Decimal(str(params["pg_amount"])) if params.get("pg_amount") not in (None, "") else None
        except InvalidOperation:
            amount = None

        return WebhookEvent(
            status=status,
            payment_id=params.get("pg_order_id"),
            transaction_id=params.get("pg_payment_id"),
            amount=amount,
            account_id=None,
            currency=params.get("pg_currency"),
            raw=params,
        )

    def webhook_response(self, *, path: str, status: str = "ok", description: str = "") -> str:
        """The signed XML FreedomPay expects back from your result URL.

        status: "ok" (accepted), "rejected" (only if the callback had pg_can_reject=1)
        or "error". Return it with content type application/xml.
        """
        if status not in ("ok", "rejected", "error"):
            raise ValueError("status must be 'ok', 'rejected' or 'error'")
        params = {"pg_status": status, "pg_description": description, "pg_salt": secrets.token_hex(8)}
        params["pg_sig"] = make_signature(script_name(path), params, self.secret_key)
        inner = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in params.items())
        return f'<?xml version="1.0" encoding="utf-8"?><response>{inner}</response>'


class FreedomPay(_FreedomPayBase):
    """Synchronous FreedomPay client."""

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
        failure_url: str | None = None,
        lifetime: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Payment:
        """Create a payment and return the URL of FreedomPay's payment page.

        `redirect_url` is where the customer lands after paying (`failure_url`
        after a failure, defaults to `redirect_url`). `lifetime` is in seconds.
        """
        url, params = self._build_init(
            amount=amount,
            payment_id=payment_id,
            description=description,
            redirect_url=redirect_url,
            webhook_url=webhook_url,
            failure_url=failure_url,
            lifetime=lifetime,
            extra=extra,
        )
        try:
            if self._http is not None:
                resp = self._http.post(url, data=params)
            else:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, data=params)
        except httpx.HTTPError as exc:
            raise APIError(f"FreedomPay request failed: {exc}") from exc
        return self._parse_init(resp, payment_id)


class AsyncFreedomPay(_FreedomPayBase):
    """Async FreedomPay client."""

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
        failure_url: str | None = None,
        lifetime: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> Payment:
        """Create a payment and return the URL of FreedomPay's payment page."""
        url, params = self._build_init(
            amount=amount,
            payment_id=payment_id,
            description=description,
            redirect_url=redirect_url,
            webhook_url=webhook_url,
            failure_url=failure_url,
            lifetime=lifetime,
            extra=extra,
        )
        try:
            if self._http is not None:
                resp = await self._http.post(url, data=params)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, data=params)
        except httpx.HTTPError as exc:
            raise APIError(f"FreedomPay request failed: {exc}") from exc
        return self._parse_init(resp, payment_id)
