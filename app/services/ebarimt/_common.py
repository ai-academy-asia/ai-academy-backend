"""eBarimt config access, PosAPI / taxpayer-directory clients and error mapping."""
from __future__ import annotations

from flask import current_app

from app.ebarimt import EBarimtError, PosAPIClient, TaxpayerLookup

from ..errors import ServiceError, from_integration_error


# ------------------------------------------------------------------- config
def _cfg(key, default=None):
    return current_app.config.get(key, default)


def is_temp_mode() -> bool:
    return bool(_cfg("EBARIMT_TEMP_MODE"))


def _posapi() -> PosAPIClient:
    """Build a client from ``Config``. Config already guarantees every key, so no
    call-site default is repeated here — a second copy would silently drift."""
    return PosAPIClient(
        _cfg("EBARIMT_POSAPI_URL"),
        timeout=_cfg("EBARIMT_HTTP_TIMEOUT"),
        receipt_path=_cfg("EBARIMT_RECEIPT_PATH"),
        info_path=_cfg("EBARIMT_INFO_PATH"),
        send_data_path=_cfg("EBARIMT_SEND_DATA_PATH"),
    )


def _taxpayer_lookup() -> TaxpayerLookup:
    return TaxpayerLookup(
        _cfg("EBARIMT_INFO_API_URL"), timeout=_cfg("EBARIMT_HTTP_TIMEOUT")
    )


def find_taxpayer(value: str) -> dict | None:
    """Company behind a 7-digit register number or a TIN, or None.

    Raises only if the directory itself is down.
    """
    try:
        return _taxpayer_lookup().resolve(value)
    except EBarimtError as exc:
        raise _as_service_error(exc) from exc


# ------------------------------------------------------------------- helpers
def _as_bool(value) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def _as_service_error(exc: EBarimtError) -> ServiceError:
    return from_integration_error(exc, prefix="ebarimt_")
