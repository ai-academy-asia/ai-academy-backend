"""Golomt Corporate statement rows and receiving-account routing data.

Split out of :mod:`app.payments.golomt`: the normalized statement credit
(:class:`StatementTxn`), the receiving account with the courses it collects for
(:class:`GolomtAccount`), and the small parsing helpers the provider uses to map
raw statement rows. Pure data — no gateway I/O here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation


@dataclass
class StatementTxn:
    """One normalized credit line from a corporate account statement."""

    txn_id: str
    amount: Decimal
    description: str
    account: str | None = None
    posted_at: datetime | None = None
    counterparty: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class GolomtAccount:
    """A receiving account plus the courses whose fees land in it."""

    number: str
    name: str | None = None
    courses: frozenset = frozenset()  # normalized course identifiers; empty = catch-all
    is_default: bool = False

    def collects(self, *identifiers) -> bool:
        keys = {_norm(i) for i in identifiers if i}
        return bool(keys & self.courses)


def _norm(value) -> str:
    """Fold a course slug/title to a routing key: lowercase, no spaces/hyphens/underscores."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


# ---------------------------------------------------------------- small utils
def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value)[:26], fmt)
        except ValueError:
            continue
    return None


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
