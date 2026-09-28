"""Receipt lookups and the finance-dashboard summary."""
from __future__ import annotations

from app.extensions import db
from app.models import EBarimtReceipt

from ..errors import ServiceError
from ..params import get_by_id, parse_limit
from ._common import _as_bool, _cfg, is_temp_mode


# ------------------------------------------------------------------- reads
def get_receipt(receipt_id) -> EBarimtReceipt:
    receipt = get_by_id(EBarimtReceipt, receipt_id)
    if receipt is None:
        raise ServiceError(404, "receipt_not_found")
    return receipt


def list_receipts(*, status=None, temp=None, payment_id=None, limit=50):
    q = EBarimtReceipt.query
    if status:
        q = q.filter_by(status=status)
    if temp is not None:
        q = q.filter_by(is_temp_mode=_as_bool(temp))
    if payment_id and str(payment_id).isdigit():
        q = q.filter_by(payment_id=int(payment_id))
    return q.order_by(EBarimtReceipt.id.desc()).limit(parse_limit(limit)).all()


def status_summary() -> dict:
    """Quick counts for the finance dashboard (how many receipts await re-issue)."""
    counts = dict(
        db.session.query(EBarimtReceipt.status, db.func.count(EBarimtReceipt.id))
        .group_by(EBarimtReceipt.status).all()
    )
    return {
        "temp_mode": is_temp_mode(),
        "auto_issue": bool(_cfg("EBARIMT_AUTO_ISSUE")),
        "counts": {k: int(v) for k, v in counts.items()},
        "pending_reissue": int(counts.get("temp", 0)),
    }
