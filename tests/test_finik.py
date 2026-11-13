import json
import time
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kgpay import (
    APIError,
    AsyncFinik,
    Finik,
    ForeignAccountError,
    InvalidPayloadError,
    InvalidSignatureError,
    PaymentStatus,
)
from kgpay._signing import canonical_string, sign, verify
from kgpay.finik import PROD_PUBLIC_KEY, SANDBOX_PUBLIC_KEY

from .fixtures import FINIK_DOCS_WEBHOOK, LIB_PRIVATE_KEY, LIB_PUBLIC_KEY, LIB_REQUEST, LIB_SIGNATURE

ACCOUNT = "acc-shop"
WEBHOOK_PATH = "/api/webhooks/finik"


# --- signing: must match Finik byte for byte -----------------------------------


def test_signature_matches_finiks_own_library():
    r = LIB_REQUEST
    data = canonical_string(r["method"], r["path"], r["headers"], r["body"], r["query"])
    assert sign(data, LIB_PRIVATE_KEY) == LIB_SIGNATURE
    assert verify(data, LIB_SIGNATURE, LIB_PUBLIC_KEY)


def test_a_real_finik_webhook_verifies_with_finiks_production_key():
    w = FINIK_DOCS_WEBHOOK
    assert verify(canonical_string("POST", w["path"], w["headers"], w["body"]), w["signature"], PROD_PUBLIC_KEY)
    tampered = {**w["body"], "amount": 1000}
    assert not verify(canonical_string("POST", w["path"], w["headers"], tampered), w["signature"], PROD_PUBLIC_KEY)


def test_private_key_on_one_env_line_works():
    data = "post\n/x\nhost:h\n"
    assert verify(data, sign(data, LIB_PRIVATE_KEY.replace("\n", "\\n")), LIB_PUBLIC_KEY)


def test_verify_never_raises_on_garbage():
    assert not verify("x", "not-base64!!", LIB_PUBLIC_KEY)
    assert not verify("x", "AAAA", "not a pem")


# --- client setup ---------------------------------------------------------------


def _client(cls=Finik, **kw):
    params = {"api_key": "key", "account_id": ACCOUNT, "private_key": LIB_PRIVATE_KEY, "sandbox": True}
    params.update(kw)
    return cls(**params)


def test_sandbox_and_production_use_finiks_published_keys():
    assert _client(sandbox=True).public_key == SANDBOX_PUBLIC_KEY
    assert _client(sandbox=False).public_key == PROD_PUBLIC_KEY
    assert _client(sandbox=True).host == "beta.api.acquiring.averspay.kg"
    assert _client(sandbox=False).host == "api.acquiring.averspay.kg"


def test_missing_credentials_fail_fast():
    with pytest.raises(ValueError):
        Finik(api_key="", account_id=ACCOUNT, private_key=LIB_PRIVATE_KEY)


# --- creating a payment -----------------------------------------------------------


def _mock(responder, seen):
    def handler(request: httpx.Request):
        seen["request"] = request
        return responder(request)

    return httpx.MockTransport(handler)


def _assert_finik_can_verify(req: httpx.Request):
    """Do what Finik does on its side: rebuild the canonical string, check our signature."""
    body = json.loads(req.content)
    headers = {
        "Host": req.url.host,
        "x-api-key": req.headers["x-api-key"],
        "x-api-timestamp": req.headers["x-api-timestamp"],
    }
    assert verify(canonical_string("POST", "/v1/payment", headers, body), req.headers["signature"], LIB_PUBLIC_KEY)
    return body


def test_create_payment_sends_a_signed_request_and_returns_the_payment_page():
    seen = {}
    http = httpx.Client(transport=_mock(lambda r: httpx.Response(302, headers={"Location": "https://pay/abc"}), seen))
    finik = _client(http_client=http, merchant_name="My Shop")

    payment = finik.create_payment(
        amount=1500,
        payment_id="order-1",
        description="Заказ №1",
        redirect_url="https://shop.kg/thanks",
        webhook_url="https://shop.kg/api/webhooks/finik",
    )

    assert payment.url == "https://pay/abc" and payment.payment_id == "order-1"
    req = seen["request"]
    assert str(req.url) == "https://beta.api.acquiring.averspay.kg/v1/payment"
    body = _assert_finik_can_verify(req)
    assert body["Amount"] == 1500 and body["PaymentId"] == "order-1" and body["CardType"] == "FINIK_QR"
    assert body["Data"] == {
        "accountId": ACCOUNT,
        "description": "Заказ №1",
        "webhookUrl": "https://shop.kg/api/webhooks/finik",
        "name_en": "My Shop",
    }


def test_create_payment_accepts_a_json_payment_url():
    seen = {}
    http = httpx.Client(transport=_mock(lambda r: httpx.Response(201, json={"paymentUrl": "https://pay/x"}), seen))
    p = _client(http_client=http).create_payment(
        amount=Decimal(10), payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
    )
    assert p.url == "https://pay/x"


def test_finik_error_becomes_api_error_with_its_message():
    seen = {}
    resp = lambda r: httpx.Response(400, json={"StatusCode": 400, "ErrorMessage": "Invalid accountId"})
    http = httpx.Client(transport=_mock(resp, seen))
    with pytest.raises(APIError, match="Invalid accountId") as exc:
        _client(http_client=http).create_payment(
            amount=10, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )
    assert exc.value.status_code == 400


@pytest.mark.parametrize("amount", [0, -5, Decimal("10.5"), "abc"])
def test_bad_amounts_are_refused_before_any_request(amount):
    with pytest.raises(ValueError):
        _client().create_payment(
            amount=amount, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )


def test_float_amounts_are_refused():
    with pytest.raises(TypeError):
        _client().create_payment(
            amount=10.0, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )


async def test_async_client_creates_a_payment():
    seen = {}
    http = httpx.AsyncClient(
        transport=_mock(lambda r: httpx.Response(302, headers={"Location": "https://pay/a"}), seen)
    )
    p = await _client(AsyncFinik, http_client=http).create_payment(
        amount=99, payment_id="a1", description="d", redirect_url="https://r", webhook_url="https://w"
    )
    assert p.url == "https://pay/a"
    _assert_finik_can_verify(seen["request"])


# --- webhooks -------------------------------------------------------------------


@pytest.fixture
def finik_key():
    """A key pair standing in for Finik's webhook key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, pub.decode()


def _deliver(priv, body, path=WEBHOOK_PATH):
    """Headers + raw bytes, exactly what Finik POSTs."""
    headers = {"host": "shop.kg", "content-type": "application/json", "x-api-timestamp": str(int(time.time() * 1000))}
    headers["signature"] = sign(canonical_string("POST", path, headers, body), priv)
    return headers, json.dumps(body, ensure_ascii=False).encode()


def _success(**over):
    body = {
        "status": "succeeded",
        "amount": 1500,
        "transactionId": "t-1",
        "fields": {"paymentId": "order-1"},
        "data": {"accountId": ACCOUNT},
    }
    body.update(over)
    return body


def test_genuine_success_webhook_is_parsed(finik_key):
    priv, pub = finik_key
    headers, raw = _deliver(priv, _success())
    event = _client(public_key=pub).parse_webhook(body=raw, headers=headers, path=WEBHOOK_PATH)
    assert event.succeeded and event.status is PaymentStatus.SUCCEEDED
    assert event.payment_id == "order-1" and event.transaction_id == "t-1"
    assert event.amount == Decimal(1500) and event.amount_covers(1500) and not event.amount_covers(1501)


def test_the_real_docs_webhook_parses_with_the_production_client():
    w = FINIK_DOCS_WEBHOOK
    finik = Finik(api_key="k", account_id=w["body"]["data"]["accountId"], private_key=LIB_PRIVATE_KEY)
    event = finik.parse_webhook(body=w["body"], headers={**w["headers"], "signature": w["signature"]}, path=w["path"])
    assert event.succeeded and event.payment_id == "141fc797-0366-480e-8ba7-2982632b2b2c" and event.amount == 1


def test_tampered_amount_is_rejected(finik_key):
    priv, pub = finik_key
    headers, _ = _deliver(priv, _success())
    forged = json.dumps(_success(amount=1)).encode()
    with pytest.raises(InvalidSignatureError):
        _client(public_key=pub).parse_webhook(body=forged, headers=headers, path=WEBHOOK_PATH)


def test_missing_signature_is_rejected(finik_key):
    _, pub = finik_key
    with pytest.raises(InvalidSignatureError):
        _client(public_key=pub).parse_webhook(body=_success(), headers={"host": "shop.kg"}, path=WEBHOOK_PATH)


def test_wrong_path_does_not_verify(finik_key):
    """Behind a proxy that strips /api, passing the internal path breaks verification."""
    priv, pub = finik_key
    headers, raw = _deliver(priv, _success())
    with pytest.raises(InvalidSignatureError):
        _client(public_key=pub).parse_webhook(body=raw, headers=headers, path="/webhooks/finik")


def test_payment_to_another_merchant_is_refused(finik_key):
    """Finik signs for all merchants with one key: someone paying THEMSELVES with
    your payment_id must not unlock your order."""
    priv, pub = finik_key
    headers, raw = _deliver(priv, _success(data={"accountId": "acc-attacker"}))
    with pytest.raises(ForeignAccountError) as exc:
        _client(public_key=pub).parse_webhook(body=raw, headers=headers, path=WEBHOOK_PATH)
    assert exc.value.account_id == "acc-attacker"


def test_failed_and_unknown_statuses(finik_key):
    priv, pub = finik_key
    finik = _client(public_key=pub)
    headers, raw = _deliver(priv, _success(status="declined"))
    assert finik.parse_webhook(body=raw, headers=headers, path=WEBHOOK_PATH).status is PaymentStatus.FAILED
    headers, raw = _deliver(priv, _success(status="processing"))
    assert finik.parse_webhook(body=raw, headers=headers, path=WEBHOOK_PATH).status is PaymentStatus.UNKNOWN


def test_missing_amount_never_covers_the_price(finik_key):
    priv, pub = finik_key
    body = _success()
    del body["amount"]
    headers, raw = _deliver(priv, body)
    event = _client(public_key=pub).parse_webhook(body=raw, headers=headers, path=WEBHOOK_PATH)
    assert event.amount is None and not event.amount_covers(1)


def test_non_json_body_is_rejected(finik_key):
    _, pub = finik_key
    with pytest.raises(InvalidPayloadError):
        _client(public_key=pub).parse_webhook(body=b"not json", headers={"signature": "x"}, path=WEBHOOK_PATH)
