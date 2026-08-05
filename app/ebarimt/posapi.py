"""Thin client for the eBarimt **PosAPI** (tax authority local REST service).

PosAPI runs as a local daemon next to the app (default ``http://localhost:7080``)
and exposes a small REST surface. This client only speaks HTTP — deciding *whether*
to call it (temp mode vs live) and persisting the result is the service layer's job.

PosAPI 3.0 surface used here::

    GET    /rest/info      — POS registration info (merchant / district / posNo)
    POST   /rest/receipt   — issue a receipt → { id (DDTD), qrData, lottery, ... }
    DELETE /rest/receipt   — return / void a previously issued receipt
    GET    /rest/sendData  — flush locally-issued receipts to the tax authority
                             (batch; issuance via /rest/receipt is real-time, this
                             sync to the ITC server runs on its own cadence)

NOTE: PosAPI versions differ slightly (2.x vs 3.0) in field names and paths.
Paths are overridable via config so this can target the test PosAPI or a specific
merchant build without code changes.
"""
from __future__ import annotations

import requests

from app.httpjson import request_json

_JSON = {"Content-Type": "application/json"}


class EBarimtError(Exception):
    """A PosAPI call failed (service down, or receipt rejected)."""

    def __init__(self, message: str, *, detail=None, retriable: bool = False):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.retriable = retriable


class PosAPIClient:
    """Defaults live in ``Config``, not here — a second set of fallbacks would be
    unreachable state that silently drifts from the real ones."""

    def __init__(self, base_url: str, *, timeout: int = 15,
                 receipt_path: str = "/rest/receipt",
                 info_path: str = "/rest/info",
                 send_data_path: str = "/rest/sendData"):
        self.base_url = base_url.rstrip("/")
        self.timeout = int(timeout)
        self.receipt_path = receipt_path
        self.info_path = info_path
        self.send_data_path = send_data_path
        # Keep-alive matters for reissue-all, which walks up to 200 receipts.
        self.session = requests.Session()

    def _fail(self, code: str, detail, retriable: bool) -> EBarimtError:
        return EBarimtError(f"posapi_{code}", detail=detail, retriable=retriable)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        return request_json(
            method, f"{self.base_url}{path}", timeout=self.timeout,
            fail=self._fail, session=self.session, **kwargs,
        )

    def info(self) -> dict:
        return self._request("GET", self.info_path)

    def create_receipt(self, payload: dict) -> dict:
        return self._request("POST", self.receipt_path, json=payload, headers=_JSON)

    def return_receipt(self, ebarimt_id: str, *, date: str | None = None) -> dict:
        """Void a receipt. ``date`` is optional (PosAPI accepts an id-only body),
        but when given it MUST be a full ``YYYY-MM-DD HH:MM:SS`` — PosAPI parses it
        with Go's ``2006-01-02 15:04:05`` layout and a bare ``YYYY-MM-DD`` fails
        with ``cannot parse "" as "15"``, so widen it rather than pass it through.
        Note PosAPI is not idempotent here: voiding the same id twice returns
        ``500 UNIQUE constraint failed: receipt.id``.
        """
        body = {"id": ebarimt_id}
        if date:
            date = str(date).strip()
            if len(date) == 10:
                date = f"{date} 00:00:00"
            body["date"] = date
        return self._request("DELETE", self.receipt_path, json=body, headers=_JSON)

    def send_data(self) -> dict:
        """Flush locally-issued receipts to the tax authority (batch sync)."""
        return self._request("GET", self.send_data_path)
