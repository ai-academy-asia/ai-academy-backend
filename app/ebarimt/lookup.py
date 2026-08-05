"""Taxpayer lookup against the tax authority's public directory.

Separate from :mod:`app.ebarimt.posapi`: PosAPI is the local daemon that issues
receipts, this is a public cloud endpoint that answers "whose number is this?".
It needs no credentials.

Two numbers matter and they are not the same one:

- **регистрийн дугаар** — a company's 7-digit registration number. This is what
  a buyer knows and can read off their paperwork.
- **ТТД** — the 11-14 digit taxpayer number. This is the only thing PosAPI will
  accept as ``customerTin`` (``/Шалгасан нөхцөл: [0-9]{11,14}/``).

So a B2B receipt starts from a register number the buyer types and needs the TIN
behind it; :meth:`TaxpayerLookup.resolve` does that hop, then confirms the name
so the buyer can see whose receipt they are about to be issued.
"""
from __future__ import annotations

import re

import requests

from app.httpjson import request_json

from .posapi import EBarimtError

DEFAULT_BASE_URL = "https://api.ebarimt.mn"
INFO_PATH = "/api/info/check/getInfo"          # ?tin=   -> name, VAT status
TIN_PATH = "/api/info/check/getTinInfo"        # ?regNo= -> the TIN

REGISTER_RE = re.compile(r"^\d{7}$")
TIN_RE = re.compile(r"^\d{11,14}$")


class TaxpayerLookup:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, timeout: int = 15):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = int(timeout)
        self.session = requests.Session()

    def _fail(self, code: str, detail, retriable: bool) -> EBarimtError:
        return EBarimtError(f"taxinfo_{code}", detail=detail, retriable=retriable)

    def _get(self, path: str, **params) -> dict:
        return request_json(
            "GET", f"{self.base_url}{path}", timeout=self.timeout,
            fail=self._fail, session=self.session, params=params,
        )

    def tin_for_register(self, register: str) -> str | None:
        """The TIN behind a 7-digit company register, or None.

        The directory answers HTTP 200 with ``status: 500`` for a number it does
        not know, so "not found" has to be read out of the body.
        """
        body = self._get(TIN_PATH, regNo=(register or "").strip())
        tin = body.get("data")
        return str(tin) if body.get("status") == 200 and tin else None

    def info_for_tin(self, tin: str) -> dict | None:
        body = self._get(INFO_PATH, tin=(tin or "").strip())
        data = body.get("data") or {}
        if body.get("status") != 200 or not data.get("found"):
            return None
        return data

    def resolve(self, value: str) -> dict | None:
        """Company behind a register number *or* a TIN.

        Returns the TIN as well as the name, because the caller needs the TIN to
        file the receipt and the name to show the buyer what they picked.
        """
        value = (value or "").strip()
        register, tin = None, None
        if REGISTER_RE.match(value):
            register, tin = value, self.tin_for_register(value)
        elif TIN_RE.match(value):
            tin = value
        if not tin:
            return None

        data = self.info_for_tin(tin)
        if data is None:
            return None
        return {
            "register": register,
            "tin": tin,
            "name": data.get("name"),
            "vat_payer": bool(data.get("vatPayer")),
            "city_payer": bool(data.get("cityPayer")),
            "is_government": bool(data.get("isGovernment")),
        }
