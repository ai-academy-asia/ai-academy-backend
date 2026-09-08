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

from datetime import datetime
from decimal import Decimal

from flask import current_app

from app import mail
from app.ebarimt import EBarimtError, PosAPIClient, TaxpayerLookup
from app.extensions import db
from app.models import (
    ACTOR_STUDENT,
    AuthAccount,
    EBarimtReceipt,
    Invoice,
    Payment,
    SeatBooking,
    Student,
)
from app.timeutil import from_local, local
from app.utils import dig

from .errors import ServiceError, from_integration_error


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


# PosAPI's declared payment codes (from /rest/info -> paymentTypes) that our
# internal Payment.method values map onto. "other"/anything unmapped -> PAYMENT_CARD.
_PAYMENT_CODE_BY_METHOD = {
    "qr": "BANK_TRANSFER_QPAY",
    "card": "PAYMENT_CARD",
    "loan": "PAYMENT_CARD",
    "transfer": "BANK_TRANSFER",
}


# ------------------------------------------------------------------- taxes
def compute_taxes(total: Decimal) -> tuple[Decimal, Decimal]:
    """Return (vat, city_tax) for a VAT-inclusive gross price.

    Mongolia: 10% VAT included in the price → vat = gross / 11. Education services
    may be VAT-exempt; set ``EBARIMT_VAT_INCLUDED=false`` to zero it out. City tax
    defaults to 0 (не applies to tuition); configurable rate on the net.
    """
    total = Decimal(str(total))
    if _cfg("EBARIMT_VAT_INCLUDED"):
        vat = (total / Decimal(11)).quantize(Decimal("0.01"))
    else:
        vat = Decimal("0.00")
    city_rate = Decimal(str(_cfg("EBARIMT_CITY_TAX_RATE")))
    if city_rate:
        net = total - vat
        city_tax = (net * city_rate / Decimal(100)).quantize(Decimal("0.01"))
    else:
        city_tax = Decimal("0.00")
    return vat, city_tax


# ------------------------------------------------------------- payload build
def build_payload(receipt: EBarimtReceipt, *, description: str, payment: Payment = None) -> dict:
    """A verified PosAPI **3.0** receipt body (nested receipts[]/items[]/payments[],
    ``type`` + ``taxType`` enums — NOT the flat 2.0 ``stocks[]``/``billType`` shape).
    Confirmed end-to-end against a live PosAPI 3.2.45 staging instance on
    2026-08-05 (real DDTD + lottery + QR returned). PosAPI rejects a missing
    ``type`` ("receipt.type утга тодорхойлогдоогүй байна") and an unregistered
    ``merchantTin`` ("PosAPI-н ААН-н жагсаалтанд '<tin>' ТТД бүртгэлгүй байна").

    The merchant list is **pulled from the tax authority**, not editable locally:
    ``:7080/web`` only picks the operator. To register a merchant you add it under
    the operator at ``st-operator.ebarimt.mn`` (prod: ``operator.ebarimt.mn``),
    approve the pending request as that merchant in the e-invoice portal
    (``stg-invoice.ebarimt.mn`` -> PosAPI систем -> ПОС холболтын бүртгэл), then
    call ``GET /rest/sendData`` locally to sync it down.

    Stored verbatim in temp mode, POSTed in live mode.

    ``payment`` should be passed explicitly by callers that haven't flushed
    ``receipt`` to the session yet — ``receipt.payment`` (the ORM relationship)
    only resolves once the object is persisted/queryable, so relying on it for a
    still-transient receipt silently reads back ``None`` and every payment
    method falls through to the ``PAYMENT_CARD`` default.
    """
    total = float(receipt.total_amount)
    vat = float(receipt.vat_amount or 0)
    city_tax = float(receipt.city_tax_amount or 0)
    tin = _cfg("EBARIMT_MERCHANT_TIN") or ""
    tax_type = "VAT_ABLE" if vat > 0 else "VAT_FREE"
    payment = payment or receipt.payment

    item = {
        "name": description,
        # barCodeType is MANDATORY even for goods without a barcode — omitting it
        # gets the item rejected with the misleading "<name> бүтээгдэхүүний barCode
        # талбарын утга хоосон байна" (the complaint is about the *type*, not the
        # code: with barCodeType=UNDEFINED an empty/absent barCode is accepted).
        # Verified against live PosAPI 3.2.45 on 2026-08-05.
        "barCode": "",
        "barCodeType": "UNDEFINED",
        "measureUnit": "ш",
        "qty": 1,
        "unitPrice": total,
        "totalAmount": total,
        "totalVAT": vat,
        "totalCityTax": city_tax,
    }
    classification_code = _cfg("EBARIMT_CLASSIFICATION_CODE")
    if classification_code:
        item["classificationCode"] = classification_code
    tax_product_code = _cfg("EBARIMT_TAX_PRODUCT_CODE")
    if tax_product_code:
        item["taxProductCode"] = tax_product_code

    payment_code = _PAYMENT_CODE_BY_METHOD.get(
        payment.method if payment else None, "PAYMENT_CARD"
    )

    payload = {
        "totalAmount": total,
        "totalVAT": vat,
        "totalCityTax": city_tax,
        "branchNo": _cfg("EBARIMT_BRANCH_NO"),
        "districtCode": receipt.district_code or "",
        "posNo": receipt.pos_no or "",
        "merchantTin": tin,
        "type": receipt.type,
        "receipts": [
            {
                "totalAmount": total,
                "totalVAT": vat,
                "totalCityTax": city_tax,
                "taxType": tax_type,
                "merchantTin": tin,
                "items": [item],
            }
        ],
        "payments": [
            {"code": payment_code, "paidAmount": total, "status": "PAID"},
        ],
    }
    # customerTin identifies the *buying company* and belongs to a B2B document
    # only. PosAPI rejects a B2C receipt that carries one: "Баримтын type
    # талбарын утга B2C_RECEIPT ... үед receipt.customerTin талбарт утга
    # дамжуулахгүй." An individual's own register number has no place on the
    # receipt at all — they claim it by scanning the QR.
    if receipt.type == "B2B_RECEIPT" and receipt.customer_register:
        payload["customerTin"] = receipt.customer_register
    return payload


# ----------------------------------------------------------------- issuance
def issue_for_payment(payment: Payment, *, type_="B2C_RECEIPT", customer_register=None,
                      description=None) -> EBarimtReceipt:
    """Create (temp) or issue (live) an eBarimt receipt for a payment.

    Raises ServiceError on a live-mode PosAPI failure; in temp mode it always
    succeeds. Idempotent: returns the existing receipt if one already exists.
    """
    # Newest first: after a partial refund a payment carries the returned
    # original *and* the replacement, and the live one is the current truth.
    existing = (EBarimtReceipt.query.filter_by(payment_id=payment.id)
                .order_by(EBarimtReceipt.id.desc()).first())
    if existing is not None:
        return existing
    if type_ not in ("B2C_RECEIPT", "B2B_RECEIPT"):
        raise ServiceError(400, "invalid_receipt_type")
    if type_ == "B2B_RECEIPT" and not customer_register:
        raise ServiceError(400, "customer_register_required")

    total = Decimal(str(payment.amount))
    vat, city_tax = compute_taxes(total)
    description = description or (payment.invoice.description if payment.invoice else None) \
        or f"AIAA payment {payment.id}"

    receipt = EBarimtReceipt(
        payment_id=payment.id,
        invoice_id=payment.invoice_id,
        type=type_,
        customer_register=customer_register,
        total_amount=total,
        vat_amount=vat,
        city_tax_amount=city_tax,
        district_code=_cfg("EBARIMT_DISTRICT_CODE"),
        pos_no=_cfg("EBARIMT_POS_NO"),
        is_temp_mode=True,
        status="temp",
    )
    payload = build_payload(receipt, description=description, payment=payment)
    receipt.raw = payload

    if not is_temp_mode():
        _send_to_posapi(receipt, payload)

    _persist_or_void(receipt)
    # After commit: the receipt is durable before we attempt delivery, so a
    # slow or failing SMTP hop can't take the issued receipt down with it.
    if not receipt.is_temp_mode:
        _email_receipt_quietly(receipt)
    return receipt


def _persist_or_void(receipt: EBarimtReceipt) -> None:
    """Store the receipt row, and hand the DDTD back if that fails.

    The receipt is minted at the tax authority *before* its row is committed —
    it has to be, since the DDTD is what we store. So a failed insert leaves the
    tax authority holding a receipt our books have no trace of, which nothing
    later can reconcile: no local row means no DDTD to void by. Undo it while we
    still know the number, and if even that fails, log the DDTD plainly — it is
    then the only way to find the receipt again.
    """
    ddtd = None if receipt.is_temp_mode else receipt.ebarimt_id
    try:
        db.session.add(receipt)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if ddtd:
            try:
                _posapi().return_receipt(ddtd)
            except EBarimtError:
                current_app.logger.error(
                    "eBarimt receipt %s was issued but neither stored nor voided — "
                    "void it by hand at the PosAPI", ddtd,
                )
        raise


def _send_to_posapi(receipt: EBarimtReceipt, payload: dict, *, client: PosAPIClient = None):
    """Post to the live PosAPI and stamp the DDTD / QR / lottery onto the receipt.

    ``client`` lets a batch reuse one connection instead of reconnecting per row.
    """
    try:
        resp = (client or _posapi()).create_receipt(payload)
    except EBarimtError as exc:
        raise _as_service_error(exc) from exc
    ddtd = resp.get("id") or resp.get("billId") or resp.get("ddtd")
    if not ddtd:
        raise ServiceError(502, "ebarimt_no_ddtd", internal=resp)
    receipt.is_temp_mode = False
    receipt.status = "issued"
    receipt.ebarimt_id = str(ddtd)
    receipt.lottery = resp.get("lottery")
    receipt.qr_data = resp.get("qrData") or resp.get("qr_data")
    # The receipt exists at the moment the tax authority says it does, not the
    # moment our HTTP call returned. Storing our own clock leaves the two
    # disagreeing by however long the round trip took — and every later
    # comparison (a void's date, a reconciliation, "when was this sold?") is
    # then off by that much. Fall back to ours only if the response has none.
    receipt.issued_at = from_local(resp.get("date")) or datetime.utcnow()
    receipt.raw = {"request": payload, "response": resp}


def issue_if_enabled(payment: Payment) -> EBarimtReceipt | None:
    """Best-effort auto-issue on settlement. Never raises — a receipt failure must
    not undo a confirmed payment. Called by the payments settle flow.

    Skipped for public checkouts: we do not yet know whether the buyer wants the
    receipt in their own name or their company's, and a B2B receipt needs the
    company's TIN. Those are issued once the buyer answers, via
    ``enrolment.set_receipt_customer``.
    """
    if not _cfg("EBARIMT_AUTO_ISSUE"):
        return None
    if _is_public_checkout(payment):
        return None
    try:
        return issue_for_payment(payment)
    except Exception as exc:  # noqa: BLE001 — deliberately swallow; settlement wins
        db.session.rollback()
        current_app.logger.warning("eBarimt auto-issue failed for payment %s: %s", payment.id, exc)
        return None


def _is_public_checkout(payment: Payment) -> bool:
    """True when this payment came from the anonymous enrolment funnel."""
    from app.models import SeatBooking  # local import keeps the module import-light

    if not payment.invoice_id:
        return False
    return SeatBooking.query.filter_by(invoice_id=payment.invoice_id).first() is not None


# ------------------------------------------------------------------- reissue
def _replay_payload(receipt: EBarimtReceipt) -> dict:
    """Rebuild a temp receipt's PosAPI body in the *current* payload shape.

    ``receipt.raw`` is the audit record of what we captured at temp time, not a
    replay source: a payload stored months earlier can predate PosAPI's field
    requirements (e.g. the mandatory ``barCodeType``, discovered 2026-08-05) or
    even be the old flat 2.0 ``stocks[]`` body, and would be rejected on reissue.
    Only the human-entered description is carried across.
    """
    return build_payload(receipt, description=_description_of(receipt))


def _description_of(receipt: EBarimtReceipt) -> str:
    """The human-entered line item, read back out of whichever payload shape we
    stored it in (3.0 nested items, legacy 2.0 stocks, or a bare request/response
    envelope written by :func:`_send_to_posapi`)."""
    raw = receipt.raw if isinstance(receipt.raw, dict) else {}
    return (
        dig(raw, "receipts", 0, "items", 0, "name")               # 3.0
        or dig(raw, "request", "receipts", 0, "items", 0, "name")  # issued: {request,response}
        or dig(raw, "stocks", 0, "name")                          # legacy 2.0
        or f"AIAA payment {receipt.payment_id}"
    )


def reissue(receipt: EBarimtReceipt) -> EBarimtReceipt:
    """Replay a temp receipt to the now-live PosAPI (once merchant rights arrive)."""
    if not receipt.is_temp_mode:
        raise ServiceError(409, "already_issued")
    if is_temp_mode():
        raise ServiceError(409, "still_in_temp_mode")
    _send_to_posapi(receipt, _replay_payload(receipt))
    db.session.commit()
    return receipt


def reissue_all_temp(limit: int = 200) -> dict:
    """Bulk-replay every temp receipt to the live PosAPI. Returns a summary."""
    if is_temp_mode():
        raise ServiceError(409, "still_in_temp_mode")
    rows = EBarimtReceipt.query.filter_by(is_temp_mode=True, status="temp").limit(limit).all()
    issued, failed = 0, []
    client = _posapi()  # one keep-alive session for the whole batch, not one per row
    for r in rows:
        try:
            _send_to_posapi(r, _replay_payload(r), client=client)
            db.session.commit()
            issued += 1
        except ServiceError as exc:
            db.session.rollback()
            failed.append({"receipt_id": r.id, "error": exc.code})
    return {"candidates": len(rows), "issued": issued, "failed": failed}


# -------------------------------------------------------- receipt delivery
def _recipient_for(receipt: EBarimtReceipt) -> tuple[str | None, str]:
    """(email, display name) of whoever paid, or (None, "").

    Two kinds of buyer reach this point and they carry their address in
    different places:

    - an enrolled **student** — no email column of their own, credentials live
      in ``auth_accounts``, so the profile gives the name and the account the
      address;
    - an anonymous **public checkout** — no account at all, the address is on
      the ``ClassroomRequest`` the buyer filled in.

    Checking only the first is why public bookings failed with
    ``no_recipient_email`` despite having an email on file.
    """
    invoice = receipt.payment.invoice if receipt.payment else None
    if invoice is None and receipt.invoice_id:
        invoice = db.session.get(Invoice, receipt.invoice_id)
    if invoice is None:
        return None, ""

    student_id = invoice.student_id
    if student_id:
        student = db.session.get(Student, student_id)
        name = (" ".join(filter(None, [student.first_name, student.last_name]))
                if student else "")
        account = AuthAccount.query.filter_by(
            actor_type=ACTOR_STUDENT, actor_id=student_id
        ).first()
        if account is not None:
            return account.email, name

    booking = SeatBooking.query.filter_by(invoice_id=invoice.id).first()
    request = booking.request if booking is not None else None
    if request is not None and request.email:
        return request.email, request.name or ""
    return None, ""


def email_receipt(receipt: EBarimtReceipt, *, to: str | None = None) -> dict:
    """Send the issued receipt to the student (or an explicit address).

    Refuses temp receipts: they carry no DDTD, lottery or QR, so the mail would
    show a receipt that does not legally exist yet.
    """
    if receipt.is_temp_mode or not receipt.ebarimt_id:
        raise ServiceError(409, "receipt_not_issued")
    if not mail.is_configured():
        raise ServiceError(503, "mail_not_configured")

    address, name = _recipient_for(receipt)
    address = to or address
    if not address:
        raise ServiceError(422, "no_recipient_email")

    message = mail.build_receipt_email(
        receipt, to=address,
        merchant_name=_cfg("MERCHANT_NAME"),
        merchant_tin=_cfg("EBARIMT_MERCHANT_TIN") or "",
        student_name=name,
        logo_path=_cfg("RECEIPT_LOGO_PATH"),
    )
    try:
        mail.send_message(message)
    except mail.MailError as exc:
        # Record the failure so it is answerable ("did this student get it?")
        # without grepping logs, and so the public receipt endpoint can say so.
        receipt.email_error = str(exc)[:500]
        receipt.emailed_at = None
        db.session.commit()
        raise ServiceError(502, "mail_send_failed", internal=str(exc)) from exc

    receipt.emailed_at = datetime.utcnow()
    receipt.emailed_to = address
    receipt.email_error = None
    db.session.commit()
    return {"sent": True, "to": address, "ebarimt_id": receipt.ebarimt_id}


def _email_receipt_quietly(receipt: EBarimtReceipt) -> None:
    """Best-effort delivery. A bounced email must never undo a paid receipt —
    it can always be re-sent from /admin/ebarimt/<id>/email."""
    if not _cfg("EBARIMT_EMAIL_RECEIPT") or not mail.is_configured():
        return
    try:
        email_receipt(receipt)
    except Exception as exc:  # noqa: BLE001 — receipt already issued; delivery is secondary
        current_app.logger.warning(
            "eBarimt receipt %s issued but not emailed: %s", receipt.id, exc
        )
        if receipt.email_error is None:      # email_receipt records its own SMTP failures
            try:
                receipt.email_error = str(exc)[:500]
                db.session.commit()
            except Exception:  # noqa: BLE001 — never let bookkeeping break settlement
                db.session.rollback()


# ------------------------------------------------------- tax authority sync
def flush_to_tax_authority() -> dict:
    """Push locally-issued receipts up to the tax authority (PosAPI ``sendData``).

    Issuing a receipt is instant — PosAPI hands out a DDTD from a pre-allocated
    lottery pool without touching the tax servers — so this batch flush is the
    step that actually transmits. It must run on a schedule; see the
    ``ebarimt-sender`` service in docker-compose.yml.

    PosAPI answers 200 with an empty body, so the only meaningful confirmation is
    the ``lastSentDate`` it reports afterwards — we read it back for the caller.
    A failed read-back is not a failed flush and is reported as ``None``.
    """
    client = _posapi()
    try:
        client.send_data()
    except EBarimtError as exc:
        raise _as_service_error(exc) from exc

    try:
        info = client.info()
    except EBarimtError:
        info = {}
    return {
        "sent": True,
        "last_sent_date": info.get("lastSentDate"),
        "left_lotteries": info.get("leftLotteries"),
        "merchants": [m.get("tin") for m in (info.get("merchants") or [])],
    }


# ------------------------------------------------------------------- returns
def issued_at_for_posapi(receipt: EBarimtReceipt) -> str | None:
    """When the receipt was created, in the clock the PosAPI keeps.

    A void names the receipt it undoes by id *and* by the moment that receipt
    was written. Getting that moment wrong is not a formatting detail: the
    return is filed against a sale the tax authority timestamps differently, and
    ours are stored in UTC — handing `issued_at` over as-is would date every
    void eight hours before the receipt it cancels.

    So the figure PosAPI itself reported is preferred, verbatim: it is already
    the right clock and the right format. Only when that is missing (an older
    row, a re-issued one) is the stored UTC converted to Mongolian time.
    """
    raw = receipt.raw if isinstance(receipt.raw, dict) else {}
    stamped = dig(raw, "response", "date")
    if isinstance(stamped, str) and stamped.strip():
        return stamped.strip()
    when = local(receipt.issued_at or receipt.created_at)
    return when.strftime("%Y-%m-%d %H:%M:%S") if when else None


def return_receipt(receipt: EBarimtReceipt) -> EBarimtReceipt:
    """Void a receipt (e.g. on refund). Temp receipts are voided locally."""
    if receipt.status == "returned":
        raise ServiceError(409, "already_returned")
    if not receipt.is_temp_mode and receipt.ebarimt_id:
        try:
            _posapi().return_receipt(
                receipt.ebarimt_id, date=issued_at_for_posapi(receipt)
            )
        except EBarimtError as exc:
            raise _as_service_error(exc) from exc
    receipt.status = "returned"
    receipt.returned_at = datetime.utcnow()
    db.session.commit()
    return receipt


def issue_replacement(original: EBarimtReceipt, amount, *, description=None) -> EBarimtReceipt:
    """Receipt the part of a sale that survived a partial refund.

    eBarimt has no partial void — a receipt is returned whole — so a buyer who
    got half their money back is left holding a receipt for a sale that no longer
    exists, and the kept half has none. The fix the tax authority expects is a
    second receipt for what was actually kept, which is what this issues, linked
    to the voided one through ``replaces_receipt_id``.

    Idempotent per ``(payment, amount)``: an existing live replacement for the
    same figure is returned untouched, so a retried refund does not mint a second
    receipt for money that was only kept once.
    """
    total = Decimal(str(amount))
    if total <= 0:
        raise ServiceError(400, "replacement_amount_required")
    if original.payment_id is None:
        raise ServiceError(409, "receipt_has_no_payment", receipt_id=original.id)

    existing = next(
        (r for r in EBarimtReceipt.query.filter_by(payment_id=original.payment_id).all()
         if r.status != "returned" and Decimal(str(r.total_amount)) == total),
        None,
    )
    if existing is not None:
        return existing

    payment = original.payment or db.session.get(Payment, original.payment_id)
    vat, city_tax = compute_taxes(total)
    receipt = EBarimtReceipt(
        payment_id=original.payment_id,
        invoice_id=original.invoice_id,
        replaces_receipt_id=original.id,
        type=original.type,
        customer_register=original.customer_register,
        total_amount=total,
        vat_amount=vat,
        city_tax_amount=city_tax,
        district_code=_cfg("EBARIMT_DISTRICT_CODE"),
        pos_no=_cfg("EBARIMT_POS_NO"),
        is_temp_mode=True,
        status="temp",
    )
    payload = build_payload(
        receipt, description=description or _description_of(original), payment=payment
    )
    receipt.raw = payload

    if not is_temp_mode():
        _send_to_posapi(receipt, payload)

    _persist_or_void(receipt)
    if not receipt.is_temp_mode:
        _email_receipt_quietly(receipt)
    return receipt


# ------------------------------------------------------------------- reads
def get_receipt(receipt_id) -> EBarimtReceipt:
    receipt = db.session.get(EBarimtReceipt, receipt_id)
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
    return q.order_by(EBarimtReceipt.id.desc()).limit(min(int(limit), 200)).all()


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


# ------------------------------------------------------------------- helpers
def _as_bool(value) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def _as_service_error(exc: EBarimtError) -> ServiceError:
    return from_integration_error(exc, prefix="ebarimt_")
