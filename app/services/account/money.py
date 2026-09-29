"""A student's own money: what they owe per enrollment, their invoices, their receipts.

Read-only views over the ledger, invoices and eBarimt receipts. Everything is
scoped to the signed-in student; another student's receipt id answers 404.
"""
from __future__ import annotations

from sqlalchemy import or_

from app.extensions import db
from app.models import (
    INVOICE_STATUSES,
    EBarimtReceipt,
    Enrollment,
    Invoice,
    Payment,
    PaymentInstallment,
    StudentLedger,
)
from app.timeutil import iso

from ..errors import ServiceError
from ..params import parse_id, parse_limit


def _money(value) -> float:
    return float(value or 0)


def _installment(inst: PaymentInstallment) -> dict:
    return {
        "id": inst.id,
        "seq": inst.seq,
        "due_date": iso(inst.due_date),
        "amount": _money(inst.amount),
        "status": inst.status,
        "paid_at": iso(inst.paid_at),
    }


def _enrollment_row(enr: Enrollment, ledger, installments) -> dict:
    cohort = enr.cohort
    course = cohort.course if cohort is not None else None
    return {
        "enrollment_id": enr.id,
        "status": enr.status,
        "course": {
            "id": course.id, "slug": course.slug,
            "title": {"mn": course.title_mn, "en": course.title_en},
        } if course is not None else None,
        "cohort": {
            "id": cohort.id, "name": cohort.name,
            "start_date": iso(cohort.start_date), "end_date": iso(cohort.end_date),
        } if cohort is not None else None,
        "total_due": _money(ledger.total_due if ledger else 0),
        "total_paid": _money(ledger.total_paid if ledger else 0),
        "balance": _money(ledger.balance if ledger else 0),
        "currency": ledger.currency if ledger else (course.currency if course else "MNT"),
        "next_due_date": iso(ledger.next_due_date) if ledger else None,
        "installments": [_installment(i) for i in installments],
    }


def ledger_overview(student_id: int) -> dict:
    """Every enrollment of the student with its ledger roll-up and installments."""
    enrollments = (
        Enrollment.query.filter(Enrollment.student_id == student_id)
        .order_by(Enrollment.created_at.desc(), Enrollment.id.desc())
        .all()
    )
    ids = [e.id for e in enrollments]
    ledgers, plans = {}, {i: [] for i in ids}
    if ids:
        for row in StudentLedger.query.filter(StudentLedger.enrollment_id.in_(ids)):
            ledgers[row.enrollment_id] = row
        rows = (PaymentInstallment.query
                .filter(PaymentInstallment.enrollment_id.in_(ids))
                .order_by(PaymentInstallment.seq))
        for inst in rows:
            plans[inst.enrollment_id].append(inst)
    return {"enrollments": [_enrollment_row(e, ledgers.get(e.id), plans[e.id])
                            for e in enrollments]}


def list_invoices(student_id: int, *, status=None, limit=None) -> dict:
    """The student's invoices, newest first. The QR payload stays on the detail call."""
    q = Invoice.query.filter_by(student_id=student_id)
    if status:
        if status not in INVOICE_STATUSES:
            raise ServiceError(400, "invalid_status", allowed=list(INVOICE_STATUSES))
        q = q.filter_by(status=status)
    rows = q.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(parse_limit(limit))
    return {"invoices": [inv.to_dict(with_qr=False) for inv in rows]}


# ------------------------------------------------------------------- receipts
def _receipt(r: EBarimtReceipt) -> dict:
    """The buyer's view of a receipt — no PosAPI ``raw``, POS number or mail log."""
    return {
        "id": r.id,
        "invoice_id": r.invoice_id,
        "payment_id": r.payment_id,
        "replaces_receipt_id": r.replaces_receipt_id,
        "type": r.type,
        "customer_register": r.customer_register,
        "total_amount": _money(r.total_amount),
        "vat_amount": _money(r.vat_amount),
        "city_tax_amount": _money(r.city_tax_amount),
        "status": r.status,
        "is_temp_mode": r.is_temp_mode,
        "ebarimt_id": r.ebarimt_id,
        "lottery": r.lottery,
        "qr_data": r.qr_data,
        "created_at": iso(r.created_at),
        "issued_at": iso(r.issued_at),
        "returned_at": iso(r.returned_at),
    }


def _my_receipts(student_id: int):
    """Receipts tied to the student's invoices, directly or through the payment."""
    mine = db.session.query(Invoice.id).filter(Invoice.student_id == student_id)
    return (
        EBarimtReceipt.query
        .outerjoin(Payment, EBarimtReceipt.payment_id == Payment.id)
        .filter(or_(EBarimtReceipt.invoice_id.in_(mine), Payment.invoice_id.in_(mine)))
    )


def list_receipts(student_id: int, *, limit=None) -> dict:
    rows = (_my_receipts(student_id)
            .order_by(EBarimtReceipt.created_at.desc(), EBarimtReceipt.id.desc())
            .limit(parse_limit(limit)))
    return {"receipts": [_receipt(r) for r in rows]}


def get_receipt(student_id: int, receipt_id) -> dict:
    pk = parse_id(receipt_id)
    receipt = (_my_receipts(student_id).filter(EBarimtReceipt.id == pk).first()
               if pk is not None else None)
    if receipt is None:
        raise ServiceError(404, "receipt_not_found")
    return _receipt(receipt)
