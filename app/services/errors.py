"""Domain-level error used by the service layer.

Services raise ``ServiceError(status, code, **extra)`` instead of touching Flask.
``create_app`` registers an error handler that renders it as
``{"error": code, ...extra}`` with the given HTTP status — so routes stay thin
and services stay framework-agnostic (apart from this one exception type)."""
from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, status: int, code: str, **extra):
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra = extra


def from_integration_error(exc, *, prefix: str, **extra) -> ServiceError:
    """Translate an outbound-integration failure into an HTTP-shaped ServiceError.

    ``exc.retriable`` is the client's own judgement about whether re-issuing the
    same call could succeed, so it maps straight onto 503-vs-502. Both the
    payment gateways and PosAPI need that mapping and it must not drift, which is
    why it lives here rather than in each service.
    """
    status = 503 if getattr(exc, "retriable", False) else 502
    err = ServiceError(status, f"{prefix}{exc.message}", **extra)
    # The full body stays server-side. It is written by QPay / StorePay / PosAPI
    # and routinely names the upstream host and port, or which of our merchant
    # credentials are unset — and these errors surface on *anonymous* endpoints.
    # Only a human-readable sentence is forwarded, because the tax authority
    # rejects in Mongolian and the buyer is the one who has to act on it.
    err.internal_detail = exc.detail
    message = _human_message(exc.detail)
    if message:
        err.extra["detail"] = {"message": message}
    return err


def _human_message(detail) -> str | None:
    if not isinstance(detail, dict):
        return None
    for key in ("message", "msg", "errorDesc", "error_description"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return None
