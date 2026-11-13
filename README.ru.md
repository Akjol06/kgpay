<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Akjol06/kgpay/main/.github/assets/banner-dark.svg">
    <img alt="kgpay — платёжные системы Кыргызстана для Python" src="https://raw.githubusercontent.com/Akjol06/kgpay/main/.github/assets/banner-light.svg" width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/kgpay/"><img alt="PyPI" src="https://img.shields.io/pypi/v/kgpay?color=e8112d&label=pypi"></a>
  <a href="https://pypi.org/project/kgpay/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/kgpay?color=14161c"></a>
  <a href="https://github.com/Akjol06/kgpay/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/Akjol06/kgpay/tests.yml?label=tests"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-f2a900"></a>
</p>

<p align="center">
  <a href="README.md">English</a> · <b>Русский</b>
</p>

<p align="center">
  Приём платежей в Кыргызстане в несколько строк на Python.<br>
  Правильно подписанные запросы, проверенные вебхуки и уже закрытые дыры безопасности.
</p>

---

## Провайдеры

| Провайдер | Способы оплаты | Sync | Async | Статус |
|---|---|:-:|:-:|---|
| **[Finik](https://www.finik.kg)** | QR, банковские карты | `Finik` | `AsyncFinik` | ✅ Готово |
| **[FreedomPay](https://freedompay.kg)** | Карты, кошельки, QR | `FreedomPay` | `AsyncFreedomPay` | ✅ Готово |
| Mbank · Бакай Банк · Оптима Банк · Элдик Банк · O!Деньги | — | — | — | 🔜 [Нужна помощь](#участие) |

## Установка

```bash
pip install kgpay
```

Нужен Python 3.10+. Зависимости: только `httpx` и `cryptography`.

## Как это работает

`kgpay` — **только код**. Внутри нет аккаунтов, денег и общих ключей.

```
 ваше приложение ──▶ kgpay ──▶ API Finik / FreedomPay ──▶ деньги на ВАШ счёт мерчанта
                       ▲
               ваши ключи (.env)
```

1. Вы заключаете договор с провайдером и получаете ключи в его кабинете мерчанта.
2. Храните их у себя в `.env` и передаёте в клиент.
3. Покупатель платит провайдеру напрямую. `kgpay` подписывает запросы и проверяет ответы.

## Быстрый старт: Finik

```python
import os
from kgpay import Finik

finik = Finik(
    api_key=os.environ["FINIK_API_KEY"],
    account_id=os.environ["FINIK_ACCOUNT_ID"],
    private_key=os.environ["FINIK_PRIVATE_KEY"],  # PEM; можно одной строкой с \n
    sandbox=True,                                 # тестовая среда, без реальных денег
    merchant_name="My Shop",                      # название на странице оплаты
)

payment = finik.create_payment(
    amount=1500,                                  # целые сомы
    payment_id="order-1024",                      # ваш уникальный id, вернётся в вебхуке
    description="Заказ №1024",
    redirect_url="https://shop.kg/thanks",
    webhook_url="https://shop.kg/api/webhooks/finik",
)

print(payment.url)  # отправьте покупателя сюда
```

### Приём вебхука

```python
from fastapi import FastAPI, HTTPException, Request
from kgpay import AsyncFinik, ForeignAccountError, InvalidSignatureError

app = FastAPI()
finik = AsyncFinik(...)

@app.post("/api/webhooks/finik")
async def finik_webhook(request: Request):
    try:
        event = finik.parse_webhook(
            body=await request.body(),
            headers=request.headers,
            path="/api/webhooks/finik",  # ПУБЛИЧНЫЙ путь, который вызывает Finik
        )
    except InvalidSignatureError:
        raise HTTPException(401)
    except ForeignAccountError:
        return {"ok": True}              # подписано Finik, но деньги ушли не вам

    order = await get_order(event.payment_id)
    if event.succeeded and order and not order.paid and event.amount_covers(order.total):
        await mark_paid(order)           # идемпотентно: Finik повторяет вебхуки
    return {"ok": True}
```

Полный рабочий пример: [`examples/fastapi_app.py`](https://github.com/Akjol06/kgpay/blob/main/examples/fastapi_app.py).

## Быстрый старт: FreedomPay

```python
from kgpay import FreedomPay

fp = FreedomPay(
    merchant_id=os.environ["FREEDOMPAY_MERCHANT_ID"],
    secret_key=os.environ["FREEDOMPAY_SECRET_KEY"],
    testing=True,                                 # pg_testing_mode=1
)

payment = fp.create_payment(
    amount="1500.50",                             # до 2 знаков после запятой
    payment_id="order-1024",
    description="Заказ №1024",
    redirect_url="https://shop.kg/thanks",
    failure_url="https://shop.kg/failed",         # необязательно
    webhook_url="https://shop.kg/api/webhooks/freedompay",
)
```

FreedomPay ждёт от вашего result URL **подписанный XML-ответ**. `kgpay` собирает его сам:

```python
from fastapi import Response

PATH = "/api/webhooks/freedompay"

@app.post(PATH)
async def freedompay_webhook(request: Request):
    try:
        event = fp.parse_webhook(body=await request.body(), path=PATH)
    except InvalidSignatureError:
        raise HTTPException(401)

    if event.succeeded and event.amount_covers(order_total(event.payment_id)):
        await mark_paid(event.payment_id)

    xml = fp.webhook_response(path=PATH, status="ok")
    return Response(xml, media_type="application/xml")
```

## Подводные камни, которые kgpay закрывает

| | Проблема | Что делает kgpay |
|---|---|---|
| 🔐 | **Подписи.** У Finik RSA-SHA256 по каноничной строке, у FreedomPay — MD5 PayBox со script name. | Подпись сверена байт в байт с официальной библиотекой Finik и с настоящим боевым вебхуком из их документации. |
| 🕵️ | **Платёж на чужой счёт.** Finik подписывает вебхуки *всех* мерчантов одним ключом: валидная подпись не значит, что деньги ваши. | `parse_webhook` сверяет `accountId` и бросает `ForeignAccountError`. |
| 🧪 | **Тестовые платежи на боевом сайте.** | Боевой клиент FreedomPay отклоняет колбэки с `pg_testing_mode=1`. |
| 💰 | **Недоплата.** | `event.amount_covers(total)`; если суммы нет, она ничего не покрывает. |
| 🔢 | **Молчаливое округление.** Finik принимает только целые сомы. | Дробь или `float` сразу дают ошибку, деньги не округляются. |
| 🔀 | **Пути за прокси.** Провайдер подписывает URL, который вызвал (например `/api/...`), даже если nginx срезает `/api`. | Публичный `path` передаётся явно. |
| 🔁 | **Повторы.** Провайдеры повторяют вебхуки часами и сутками. | Описано в доках: зачисляйте идемпотентно по `payment_id`. |

## Коротко об API

```python
payment.url                  # куда отправить покупателя
payment.payment_id           # ваш id
payment.provider_payment_id  # id у провайдера (FreedomPay)

event.status                 # PaymentStatus.SUCCEEDED | FAILED | PENDING | UNKNOWN
event.succeeded              # bool
event.payment_id             # ваш id из create_payment
event.transaction_id         # id транзакции у провайдера
event.amount                 # Decimal | None
event.amount_covers(total)   # оплачено не меньше total?
event.raw                    # исходные данные целиком
```

| Исключение | Когда |
|---|---|
| `APIError` | Провайдер вернул ошибку или недоступен (`.status_code`, `.response_text`) |
| `InvalidSignatureError` | Нет подписи, она неверна, или тестовый платёж пришёл на боевой клиент |
| `ForeignAccountError` | Вебхук Finik о платеже на чужой `account_id` |
| `InvalidPayloadError` | Тело вебхука не разбирается |

Все наследуются от `KGPayError`.

## Участие

Новые провайдеры очень нужны, особенно **Mbank, Бакай Банк, Оптима Банк, Элдик Банк и O!Деньги**. Банки обычно выдают документацию API эквайринга только мерчантам, поэтому если она у вас есть, PR с клиентом и тестами — самый ценный вклад.

```bash
git clone https://github.com/Akjol06/kgpay && cd kgpay
uv sync
uv run pytest
uv run ruff check .
```

Каждый провайдер — отдельный модуль в `src/kgpay/`: sync- и async-клиент, `create_payment` и `parse_webhook`, плюс тесты, которые сверяют подписи с эталонными данными самого провайдера.

## Лицензия

[MIT](LICENSE). `kgpay` — независимый проект, не связан с Finik, AversPay и FreedomPay.
