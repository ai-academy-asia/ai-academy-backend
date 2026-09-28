"""Raising a payment request through a gateway and persisting it as an Invoice."""
from __future__ import annotations

# Look the provider up through the gateway package at call time (not a name
# imported here), so a test that patches ``app.payments.get_provider`` reaches
# every submodule of this package.
from app import payments as gateways
from app.extensions import db
from app.models import (
    Course,
    Enrollment,
    Invoice,
    PaymentInstallment,
    Student,
)
from app.payments import (
    INTERNAL_PROVIDERS,
    SUPPORTED_PROVIDERS,
    InvoiceRequest,
    PaymentGatewayError,
)

from ..errors import ServiceError
from .helpers import _as_service_error, _gen_reference, _to_amount


# --------------------------------------------------------------- create invoice
def create_invoice(
    provider: str,
    *,
    amount,
    callback_base: str,
    description: str = "",
    enrollment_id=None,
    student_id=None,
    installment_id=None,
    customer: dict | None = None,
) -> Invoice:
    """Raise a payment request through ``provider`` and persist it as an Invoice.

    ``callback_base`` is the public origin (e.g. ``https://api.ai-academy.asia``)
    used to build the gateway callback URL.
    """
    # Any provider the registry knows, including the internal sandbox stub —
    # get_provider is what refuses sandbox when PAYMENTS_SANDBOX is off. Routes
    # that take the name from a request body whitelist SUPPORTED_PROVIDERS
    # themselves; validating it twice here is what broke demo mode.
    if provider not in SUPPORTED_PROVIDERS + INTERNAL_PROVIDERS:
        raise ServiceError(400, "unsupported_provider", supported=list(SUPPORTED_PROVIDERS))
    amount = _to_amount(amount)
    customer = customer or {}

    # Resolve/validate the money-domain links and enrich the customer payload.
    enrollment_id, student_id, installment_id = _resolve_links(
        enrollment_id, student_id, installment_id
    )
    if student_id and not customer:
        customer = _customer_from_student(student_id)

    ref = _gen_reference(provider)
    callback_url = f"{callback_base.rstrip('/')}/payments/{provider}/callback?ref={ref}"
    req = InvoiceRequest(
        sender_invoice_no=ref,
        amount=amount,
        currency="MNT",
        description=description or f"AIAA payment {ref}",
        callback_url=callback_url,
        customer=customer,
        # Golomt routes to a receiving account by course; pass the course hints.
        extra=_course_hint(enrollment_id) if provider == "golomt" else {},
    )

    try:
        result = gateways.get_provider(provider).create_invoice(req)
    except PaymentGatewayError as exc:
        raise _as_service_error(exc) from exc

    invoice = Invoice(
        provider=provider,
        enrollment_id=enrollment_id,
        student_id=student_id,
        installment_id=installment_id,
        sender_invoice_no=ref,
        amount=amount,
        currency="MNT",
        description=req.description,
        status="pending",
        provider_invoice_id=result.provider_invoice_id,
        qr_text=result.qr_text,
        qr_image=result.qr_image,
        payment_url=result.payment_url,
        urls=result.urls,
        provider_meta=result.raw,
        expires_at=result.expires_at,
    )
    db.session.add(invoice)
    db.session.commit()
    return invoice


def _resolve_links(enrollment_id, student_id, installment_id):
    if installment_id:
        inst = db.session.get(PaymentInstallment, installment_id)
        if inst is None:
            raise ServiceError(404, "installment_not_found")
        # Settling marks this installment paid, so it must be the enrollment's own.
        if enrollment_id and int(enrollment_id) != inst.enrollment_id:
            raise ServiceError(400, "installment_not_in_enrollment")
        enrollment_id = enrollment_id or inst.enrollment_id
        student_id = student_id or inst.student_id
    if enrollment_id:
        enr = db.session.get(Enrollment, enrollment_id)
        if enr is None:
            raise ServiceError(404, "enrollment_not_found")
        student_id = student_id or enr.student_id
    if student_id and db.session.get(Student, student_id) is None:
        raise ServiceError(404, "student_not_found")
    return enrollment_id, student_id, installment_id


def _customer_from_student(student_id) -> dict:
    s = db.session.get(Student, student_id)
    if s is None:
        return {}
    return {
        "name": f"{s.first_name} {s.last_name or ''}".strip(),
        "phone": getattr(s, "phone", None),
        "email": getattr(s, "email", None),
        "register": getattr(s, "register", None),
    }


def _course_hint(enrollment_id) -> dict:
    """Course slug/title for an enrollment — used by Golomt to route the payment
    to the right receiving account. Empty when there's no linked course."""
    if not enrollment_id:
        return {}
    enr = db.session.get(Enrollment, enrollment_id)
    if enr is None or not enr.course_id:
        return {}
    course = db.session.get(Course, enr.course_id)
    if course is None:
        return {}
    return {
        "course_slug": course.slug,
        "course_title": course.title_mn or course.title_en,
    }
