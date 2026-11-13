from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class PaymentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Payment:
    """A created payment: send the customer to `url`."""

    payment_id: str
    url: str
    provider_payment_id: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """A verified payment result.

    `payment_id` is the id YOU passed to `create_payment`. Always compare
    `amount` with what you charged before marking an order paid.
    """

    status: PaymentStatus
    payment_id: str | None
    transaction_id: str | None
    amount: Decimal | None
    account_id: str | None
    raw: dict[str, Any] = field(repr=False)
    currency: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is PaymentStatus.SUCCEEDED

    def amount_covers(self, expected: Decimal | float | str) -> bool:
        """True when the paid amount is known and at least `expected`."""
        return self.amount is not None and self.amount >= Decimal(str(expected))
