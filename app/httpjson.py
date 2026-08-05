"""Shared JSON-over-HTTP plumbing for outbound integrations.

Both outbound clients — the payment gateways (``app/payments/base.py``) and the
tax authority's local PosAPI (``app/ebarimt/posapi.py``) — need the same three
judgements: what counts as unreachable, what counts as retriable, and how to
read a body that isn't JSON. Keeping them in one place means the 502-vs-503
mapping both services derive from ``retriable`` can't drift apart.

Each caller keeps its own exception type (and its own extra fields, like the
gateway's ``provider``) by passing a ``fail`` factory; this module never names
a specific error class.
"""
from __future__ import annotations

from typing import Callable

import requests

# Codes handed to the ``fail`` factory. Callers prefix them with their own
# namespace ("gateway_unreachable", "posapi_rejected", ...).
UNREACHABLE = "unreachable"
SERVER_ERROR = "error"
REJECTED = "rejected"

FailFactory = Callable[[str, object, bool], Exception]


def safe_body(resp) -> dict:
    """Best-effort body for an error response — JSON when it parses, a clipped
    text excerpt otherwise, so a gateway's HTML error page can't flood the log."""
    try:
        return resp.json()
    except ValueError:
        return {"status_code": resp.status_code, "text": resp.text[:500]}


def request_json(method: str, url: str, *, timeout: float, fail: FailFactory,
                 session: requests.Session | None = None, **kwargs) -> dict:
    """Perform a request and return the decoded JSON body.

    ``fail(code, detail, retriable)`` builds the exception to raise. 5xx and
    transport errors are retriable; 4xx is a decision the far side made and
    won't change on retry. A 2xx that isn't JSON comes back as ``{"_raw": text}``
    rather than raising — several PosAPI endpoints answer 200 with an empty body.
    """
    kwargs.setdefault("timeout", timeout)
    caller = session or requests
    try:
        resp = caller.request(method, url, **kwargs)
    except requests.RequestException as exc:
        raise fail(UNREACHABLE, str(exc), True) from exc
    if resp.status_code >= 500:
        raise fail(SERVER_ERROR, safe_body(resp), True)
    if resp.status_code >= 400:
        raise fail(REJECTED, safe_body(resp), False)
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text}
