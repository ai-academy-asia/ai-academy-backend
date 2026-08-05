"""eBarimt (Mongolian e-receipt) integration package.

- ``posapi``  : thin HTTP client for the tax authority's local PosAPI service.
- ``lookup``  : public taxpayer directory ("whose TIN is this?"), no credentials.
- The orchestration (temp mode, VAT calc, DB persistence) lives in
  ``app.services.ebarimt`` so this package stays framework/DB-free.
"""
from .lookup import TaxpayerLookup
from .posapi import EBarimtError, PosAPIClient

__all__ = ["EBarimtError", "PosAPIClient", "TaxpayerLookup"]
