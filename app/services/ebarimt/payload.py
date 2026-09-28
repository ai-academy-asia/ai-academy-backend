"""Tax computation and the PosAPI 3.0 receipt body."""
from __future__ import annotations

from decimal import Decimal

from app.models import EBarimtReceipt, Payment

from ._common import _cfg

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
