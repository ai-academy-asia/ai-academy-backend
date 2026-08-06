"""Domain-level error used by the service layer.

Services raise ``ServiceError(status, code, **extra)`` instead of touching Flask.
``create_app`` registers an error handler that renders it as
``{"error": code, ...extra}`` with the given HTTP status — so routes stay thin
and services stay framework-agnostic (apart from this one exception type).

Anything an upstream told us goes in ``internal=`` rather than ``**extra``. Those
bodies name our internal hosts and ports and which merchant credentials are
unset, and most of these errors surface on endpoints an anonymous buyer can
reach. ``internal`` is logged, never serialised; only a human-readable sentence
lifted out of it is forwarded, because the tax authority and the gateways write
their rejections in Mongolian and the buyer is the one who has to act on them.
"""
from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, status: int, code: str, internal=None, **extra):
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra = extra
        # Deliberately not in `extra`: `extra` is what gets serialised.
        self.internal_detail = internal
        message = human_message(internal)
        if message:
            self.extra["detail"] = {"message": message}


def human_message(detail) -> str | None:
    """The one buyer-facing sentence an upstream body carries, if any.

    A dict with a named message field only. A bare string is a stringified
    exception — an SMTP greeting, a requests URL — which is the thing this is
    supposed to keep in.
    """
    if not isinstance(detail, dict):
        return None
    for key in ("message", "msg", "errorDesc", "error_description"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return None


def from_integration_error(exc, *, prefix: str, **extra) -> ServiceError:
    """Translate an outbound-integration failure into an HTTP-shaped ServiceError.

    ``exc.retriable`` is the client's own judgement about whether re-issuing the
    same call could succeed, so it maps straight onto 503-vs-502. Both the
    payment gateways and PosAPI need that mapping and it must not drift, which is
    why it lives here rather than in each service.
    """
    status = 503 if getattr(exc, "retriable", False) else 502
    return ServiceError(
        status, f"{prefix}{exc.message}", internal=exc.detail, **extra
    )
