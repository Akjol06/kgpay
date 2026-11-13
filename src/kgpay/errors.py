class KGPayError(Exception):
    """Base error for every kgpay exception."""


class APIError(KGPayError):
    """The payment provider answered with an error."""

    def __init__(self, message: str, *, status_code: int | None = None, response_text: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class InvalidSignatureError(KGPayError):
    """A webhook's signature is missing or does not verify. Do not trust its body."""


class ForeignAccountError(KGPayError):
    """A genuinely signed webhook for a payment to a different merchant account.

    Providers like Finik sign webhooks with one key for all merchants, so a valid
    signature proves "this came from Finik", not "this money went to you".
    """

    def __init__(self, message: str, *, account_id: str | None) -> None:
        super().__init__(message)
        self.account_id = account_id


class InvalidPayloadError(KGPayError):
    """The webhook body is not a JSON object."""
