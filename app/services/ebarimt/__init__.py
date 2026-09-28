"""eBarimt receipt orchestration.

Ties a settled :class:`~app.models.payment.Payment` to a Mongolian tax receipt.
Runs in one of two modes (config ``EBARIMT_TEMP_MODE``):

- **temp mode** (default, pilot): no real PosAPI merchant rights yet. We compute
  the taxes and store an ``EBarimtReceipt`` with ``is_temp_mode=True, status=temp``
  and the exact PosAPI payload in ``raw`` — nothing is sent. Later, once the
  merchant is live, :func:`reissue` replays that payload to the real PosAPI.
- **live mode**: the payload is POSTed to the local PosAPI; the returned DDTD /
  QR / lottery number are saved and the receipt becomes ``issued``.

Receipt issuance is *best-effort* on settlement (:func:`issue_if_enabled`): a
PosAPI hiccup never rolls back a real payment — the receipt just stays for retry.
"""
from __future__ import annotations

from ._common import find_taxpayer, is_temp_mode
from .delivery import email_receipt, flush_to_tax_authority
from .issuance import issue_for_payment, issue_if_enabled, reissue, reissue_all_temp
from .payload import build_payload, compute_taxes
from .reads import get_receipt, list_receipts, status_summary
from .returns import issue_replacement, issued_at_for_posapi, return_receipt

__all__ = [
    "build_payload",
    "compute_taxes",
    "email_receipt",
    "find_taxpayer",
    "flush_to_tax_authority",
    "get_receipt",
    "is_temp_mode",
    "issue_for_payment",
    "issue_if_enabled",
    "issue_replacement",
    "issued_at_for_posapi",
    "list_receipts",
    "reissue",
    "reissue_all_temp",
    "return_receipt",
    "status_summary",
]
