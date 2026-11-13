"""RSA-SHA256 request signing used by Finik (AversPay acquiring).

The canonical string is Finik's own `python-authorizer` algorithm
(github.com/mancho-devs/python-authorizer), reimplemented on `cryptography`:

    <method, lowercase>
    <path, url-decoded>
    host:<Host>&<x-api-* headers, sorted by name, "name:value" joined by &>
    [<query: sorted "key=value" joined by &>]       <- only when there is a query
    <JSON body: top-level keys sorted, compact separators, non-ASCII kept>

Parts are joined by "\\n" and signed with PKCS#1 v1.5. The tests check this
against a signature produced by the original library and against a real
webhook from Finik's documentation.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, unquote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def _pem(value: str | bytes) -> bytes:
    """Accept a PEM as str/bytes; literal "\\n" (one-line .env values) become newlines."""
    if isinstance(value, bytes):
        value = value.decode()
    return value.replace("\\n", "\n").strip().encode()


def canonical_string(
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any] | None,
    query: Mapping[str, str | None] | None = None,
) -> str:
    """Build the exact string Finik signs."""
    host = next((v for k, v in headers.items() if k.lower() == "host"), None)
    if host is None:
        raise ValueError("Header 'Host' is required for signing")
    api_headers = sorted((k.lower(), str(v)) for k, v in headers.items() if k.lower().startswith("x-api-"))
    parts = [
        method.lower(),
        unquote(path or ""),
        "&".join([f"host:{host}", *(f"{k}:{v}" for k, v in api_headers)]),
    ]
    if query:
        parts.append("&".join(f"{quote(unquote(k))}={quote(unquote(query[k] or ''))}" for k in sorted(query)))
    parts.append(
        json.dumps({k: body[k] for k in sorted(body)}, separators=(",", ":"), ensure_ascii=False) if body else ""
    )
    return "\n".join(parts)


def sign(data: str, private_key_pem: str | bytes) -> str:
    """Sign `data` with an RSA private key (PEM). Returns base64."""
    key = serialization.load_pem_private_key(_pem(private_key_pem), password=None)
    return base64.b64encode(key.sign(data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()  # type: ignore[union-attr,call-arg]


def verify(data: str, signature: str, public_key_pem: str | bytes) -> bool:
    """Check a base64 RSA-SHA256 signature. Never raises: bad input is just False."""
    try:
        key = serialization.load_pem_public_key(_pem(public_key_pem))
        key.verify(base64.b64decode(signature), data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr,call-arg]
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
