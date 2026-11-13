import hashlib
import xml.etree.ElementTree as ET
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode

import httpx
import pytest

from kgpay import APIError, AsyncFreedomPay, FreedomPay, InvalidPayloadError, InvalidSignatureError, PaymentStatus
from kgpay.freedompay import make_signature, script_name

SECRET = "s3cret"
WEBHOOK_PATH = "/api/webhooks/freedompay"

OK_XML = """<?xml version="1.0" encoding="utf-8"?>
<response><pg_status>ok</pg_status><pg_payment_id>4567788</pg_payment_id>
<pg_redirect_url>https://customer.freedompay.kg/pay.html?customer=abc</pg_redirect_url>
<pg_redirect_url_type>need data</pg_redirect_url_type><pg_salt>x</pg_salt><pg_sig>y</pg_sig></response>"""


def _client(cls=FreedomPay, **kw):
    params = {"merchant_id": "552170", "secret_key": SECRET, "testing": True}
    params.update(kw)
    return cls(**params)


# --- signature ------------------------------------------------------------------


def test_signature_is_the_paybox_algorithm():
    params = {"pg_b": "2", "pg_a": "1", "pg_sig": "ignored"}
    assert (
        make_signature("init_payment.php", params, "SECRET") == hashlib.md5(b"init_payment.php;1;2;SECRET").hexdigest()
    )


def test_script_name_is_the_last_path_segment():
    assert script_name("/api/webhooks/freedompay") == "freedompay"
    assert script_name("https://shop.kg/pay/result/?x=1") == "result"


# --- creating a payment -----------------------------------------------------------


def _mock(responder, seen):
    def handler(request):
        seen["request"] = request
        return responder(request)

    return httpx.MockTransport(handler)


def test_create_payment_sends_a_signed_form_and_returns_the_payment_page():
    seen = {}
    http = httpx.Client(transport=_mock(lambda r: httpx.Response(200, text=OK_XML), seen))
    payment = _client(http_client=http).create_payment(
        amount=Decimal("1500.50"),
        payment_id="order-1",
        description="Заказ №1",
        redirect_url="https://shop.kg/thanks",
        webhook_url="https://shop.kg/api/webhooks/freedompay",
        lifetime=3600,
    )
    assert payment.url.startswith("https://customer.freedompay.kg/") and payment.provider_payment_id == "4567788"

    req = seen["request"]
    assert str(req.url) == "https://api.freedompay.kg/init_payment.php"
    form = dict(parse_qsl(req.content.decode()))
    # What FreedomPay does on its side: recompute pg_sig with the shared secret.
    assert form["pg_sig"] == make_signature("init_payment.php", form, SECRET)
    assert form["pg_amount"] == "1500.5" and form["pg_currency"] == "KGS" and form["pg_order_id"] == "order-1"
    assert form["pg_testing_mode"] == "1" and form["pg_lifetime"] == "3600"
    assert form["pg_failure_url"] == "https://shop.kg/thanks"


def test_rejected_init_becomes_api_error():
    xml = "<response><pg_status>error</pg_status><pg_error_description>Wrong sig</pg_error_description></response>"
    http = httpx.Client(transport=_mock(lambda r: httpx.Response(200, text=xml), {}))
    with pytest.raises(APIError, match="Wrong sig"):
        _client(http_client=http).create_payment(
            amount=10, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )


def test_non_xml_answer_becomes_api_error():
    http = httpx.Client(transport=_mock(lambda r: httpx.Response(200, text="<html>oops"), {}))
    with pytest.raises(APIError):
        _client(http_client=http).create_payment(
            amount=10, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )


@pytest.mark.parametrize("amount", [0, "0.001", "abc", -1])
def test_bad_amounts_are_refused(amount):
    with pytest.raises(ValueError):
        _client().create_payment(
            amount=amount, payment_id="p", description="d", redirect_url="https://r", webhook_url="https://w"
        )


def test_nested_extra_params_are_refused():
    with pytest.raises(TypeError):
        _client().create_payment(
            amount=10,
            payment_id="p",
            description="d",
            redirect_url="https://r",
            webhook_url="https://w",
            extra={"pg_receipt_positions": [{"count": 1}]},
        )


async def test_async_client_creates_a_payment():
    seen = {}
    http = httpx.AsyncClient(transport=_mock(lambda r: httpx.Response(200, text=OK_XML), seen))
    p = await _client(AsyncFreedomPay, http_client=http).create_payment(
        amount=99, payment_id="a1", description="d", redirect_url="https://r", webhook_url="https://w"
    )
    assert p.provider_payment_id == "4567788"


# --- webhooks -------------------------------------------------------------------


def _callback(**over):
    params = {
        "pg_order_id": "order-1",
        "pg_payment_id": "4567788",
        "pg_amount": "1500.50",
        "pg_currency": "KGS",
        "pg_result": "1",
        "pg_can_reject": "1",
        "pg_testing_mode": "1",
        "pg_salt": "abc",
    }
    params.update(over)
    params["pg_sig"] = make_signature("freedompay", params, SECRET)
    return urlencode(params).encode()


def test_genuine_success_callback_is_parsed():
    event = _client().parse_webhook(body=_callback(), path=WEBHOOK_PATH)
    assert event.succeeded and event.payment_id == "order-1" and event.transaction_id == "4567788"
    assert event.amount == Decimal("1500.50") and event.currency == "KGS" and event.amount_covers("1500.5")


@pytest.mark.parametrize(("result", "status"), [("0", PaymentStatus.FAILED), ("2", PaymentStatus.PENDING)])
def test_failed_and_pending_results(result, status):
    assert _client().parse_webhook(body=_callback(pg_result=result), path=WEBHOOK_PATH).status is status


def test_tampered_callback_is_rejected():
    body = _callback().replace(b"pg_amount=1500.50", b"pg_amount=1.00")
    with pytest.raises(InvalidSignatureError):
        _client().parse_webhook(body=body, path=WEBHOOK_PATH)


def test_wrong_script_name_does_not_verify():
    with pytest.raises(InvalidSignatureError):
        _client().parse_webhook(body=_callback(), path="/api/webhooks/result")


def test_live_client_refuses_test_payments():
    with pytest.raises(InvalidSignatureError):
        _client(testing=False).parse_webhook(body=_callback(pg_testing_mode="1"), path=WEBHOOK_PATH)
    assert _client(testing=False).parse_webhook(body=_callback(pg_testing_mode="0"), path=WEBHOOK_PATH).succeeded


def test_empty_callback_is_rejected():
    with pytest.raises(InvalidPayloadError):
        _client().parse_webhook(body=b"", path=WEBHOOK_PATH)


def test_webhook_response_is_signed_xml():
    xml = _client().webhook_response(path=WEBHOOK_PATH, status="ok", description="Order <paid>")
    fields = {el.tag: el.text or "" for el in ET.fromstring(xml)}
    assert fields["pg_status"] == "ok" and fields["pg_description"] == "Order <paid>"
    assert fields["pg_sig"] == make_signature("freedompay", fields, SECRET)
    with pytest.raises(ValueError):
        _client().webhook_response(path=WEBHOOK_PATH, status="maybe")
