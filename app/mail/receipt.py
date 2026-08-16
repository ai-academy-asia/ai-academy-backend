"""Builds the eBarimt receipt email a student receives after paying.

Two things drive the markup choices here:

- **Table layout, inline styles.** Gmail and Outlook strip or partially honour
  ``<style>`` blocks and ignore flex/grid, so the layout is nested tables with
  every rule inline. It looks dated as web code; it is what renders.
- **QR as an inline attachment, not a data: URI.** Gmail blocks ``data:`` image
  sources outright, so the QR is attached with a Content-ID and referenced as
  ``cid:qr`` — the one form that renders across clients without the recipient
  having to click "show images" on a remote host we'd otherwise need to run.
"""
from __future__ import annotations

import io
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path

import segno

from app.timeutil import local

_TYPE_LABEL = {"B2C_RECEIPT": "Хувь хүн", "B2B_RECEIPT": "Байгууллага"}

# Rendered width of the logo; height follows the source aspect ratio (3.21:1).
_LOGO_W, _LOGO_H = 160, 50
_MAX_LOGO_BYTES = 512 * 1024

_INK = "#111111"
_MUTED = "#767676"
_RULE = "#e4e4e4"


def _money(value) -> str:
    """10000 -> '10,000 ₮'. Keeps kopecks only when they exist.

    The space before ₮ is load-bearing: several sans-serif fallbacks ship the
    tugrik sign with a broken advance width and draw it on top of the preceding
    digit, which is very visible on the total line.
    """
    d = Decimal(str(value or 0))
    amount = f"{d:,.0f}" if d == d.to_integral_value() else f"{d:,.2f}"
    return f"{amount} ₮"  # non-breaking, so the amount never wraps away from ₮


def _items_from(receipt) -> list[dict]:
    """Line items out of the stored payload.

    ``raw`` is the temp payload before issuing and ``{"request", "response"}``
    after, so look in both. Falls back to a single synthetic line so the email
    is never blank for a receipt whose payload we can't parse.
    """
    raw = receipt.raw if isinstance(receipt.raw, dict) else {}
    payload = raw.get("request") if isinstance(raw.get("request"), dict) else raw
    try:
        items = payload["receipts"][0]["items"]
    except (KeyError, IndexError, TypeError):
        items = []
    out = []
    for it in items or []:
        if isinstance(it, dict) and it.get("name"):
            out.append({
                "name": it["name"],
                "qty": it.get("qty", 1),
                "total": it.get("totalAmount", receipt.total_amount),
            })
    return out or [{"name": "Сургалтын төлбөр", "qty": 1, "total": receipt.total_amount}]


def _row(label: str, value: str, *, mono: bool = False) -> str:
    family = "'SFMono-Regular',Consolas,monospace" if mono else "inherit"
    size = "12px" if mono else "13px"
    return (
        f'<tr>'
        f'<td style="padding:5px 12px 5px 0;color:{_MUTED};font-size:13px;'
        f'white-space:nowrap;vertical-align:top;">{label}</td>'
        f'<td style="padding:5px 0;color:{_INK};font-size:{size};'
        f'font-family:{family};word-break:break-all;">{value}</td>'
        f'</tr>'
    )


def _read_logo(path: str | None) -> bytes | None:
    """Logo bytes, or None if there's no usable file — the header then falls back
    to the merchant name as text rather than showing a broken image."""
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    # Guard the size: an oversized logo bloats every receipt we send.
    return data if 0 < len(data) <= _MAX_LOGO_BYTES else None


def build_receipt_email(receipt, *, to: str, merchant_name: str,
                        merchant_tin: str, student_name: str = "",
                        logo_path: str | None = None) -> EmailMessage:
    """A ready-to-send receipt email. Raises nothing — validation is the caller's."""
    logo = _read_logo(logo_path)
    # Stored UTC, read by a buyer in Ulaanbaatar: print their wall clock, not ours.
    issued = local(receipt.issued_at or receipt.created_at)
    date_str = issued.strftime("%Y-%m-%d") if issued else "-"
    time_str = issued.strftime("%H:%M:%S") if issued else "-"
    items = _items_from(receipt)
    total = _money(receipt.total_amount)

    item_rows = "".join(
        f'<tr>'
        f'<td style="padding:9px 0;border-bottom:1px solid {_RULE};font-size:13px;'
        f'color:{_INK};">{it["name"]}</td>'
        f'<td style="padding:9px 8px;border-bottom:1px solid {_RULE};font-size:13px;'
        f'color:{_MUTED};text-align:center;">{it["qty"]}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {_RULE};font-size:13px;'
        f'color:{_INK};text-align:right;white-space:nowrap;">{_money(it["total"])}</td>'
        f'</tr>'
        for it in items
    )

    details = (
        _row("Төрөл:", _TYPE_LABEL.get(receipt.type, receipt.type or "-"))
        + _row("ТТД:", merchant_tin or "-", mono=True)
        + (_row("Худалдан авагч ТТД:", receipt.customer_register, mono=True)
           if receipt.customer_register else "")
        + _row("ДДТД:", receipt.ebarimt_id or "-", mono=True)
        + _row("Огноо:", f"{date_str} &nbsp;&nbsp;Цаг: {time_str}")
    )

    tax_rows = ""
    if receipt.vat_amount:
        tax_rows += _row("НӨАТ:", _money(receipt.vat_amount))
    if receipt.city_tax_amount:
        tax_rows += _row("Хотын татвар:", _money(receipt.city_tax_amount))
    tax_block = (
        '<tr><td style="padding:10px 28px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%">{tax_rows}</table></td></tr>'
    ) if tax_rows else ""

    greeting = f"Сайн байна уу, {student_name}." if student_name else "Сайн байна уу."

    # alt text carries the brand when images are off, so the header never reads blank.
    header = (
        f'<img src="cid:logo" width="{_LOGO_W}" height="{_LOGO_H}" alt="{merchant_name}"'
        f' style="display:block;margin:0 auto;border:0;'
        f'width:{_LOGO_W}px;height:{_LOGO_H}px;"/>'
    ) if logo else (
        f'<div style="font-size:15px;font-weight:700;letter-spacing:.08em;'
        f'color:{_INK};">{merchant_name}</div>'
    )

    # The MIME part already declares charset=utf-8, but some desktop clients
    # (older Outlook especially) sniff the body instead and mangle Cyrillic —
    # the meta tag costs nothing and removes that failure mode.
    html = f"""\
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;">
<div style="margin:0;padding:24px 12px;background:#f2f3f5;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="420"
       style="width:420px;max-width:100%;background:#ffffff;border-radius:10px;
              font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
  <tr><td style="padding:28px 28px 0;text-align:center;">
    {header}
  </td></tr>

  <tr><td style="padding:22px 28px 4px;text-align:center;">
    <div style="font-size:25px;font-weight:700;color:{_INK};">Нийт дүн: {total}</div>
  </td></tr>
  <tr><td style="padding:0 28px 20px;text-align:center;">
    <div style="font-size:12px;color:{_MUTED};">Төлбөрийн баримт амжилттай үүслээ.</div>
  </td></tr>

  <tr><td style="padding:0 28px;">
    <div style="border-top:2px solid {_INK};"></div></td></tr>

  <tr><td style="padding:18px 28px 0;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
      {details}
    </table>
  </td></tr>

  <tr><td style="padding:16px 28px 0;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
      <tr>
        <th align="left"   style="padding:0 0 6px;font-size:11px;color:{_MUTED};
            font-weight:600;text-transform:uppercase;letter-spacing:.05em;
            border-bottom:1px solid {_RULE};">Үйлчилгээ</th>
        <th align="center" style="padding:0 8px 6px;font-size:11px;color:{_MUTED};
            font-weight:600;border-bottom:1px solid {_RULE};">Тоо</th>
        <th align="right"  style="padding:0 0 6px;font-size:11px;color:{_MUTED};
            font-weight:600;border-bottom:1px solid {_RULE};">Дүн</th>
      </tr>
      {item_rows}
      <tr>
        <td colspan="2" style="padding:12px 0 0;font-size:14px;font-weight:700;
            color:{_INK};">Дүн:</td>
        <td style="padding:12px 0 0;font-size:14px;font-weight:700;color:{_INK};
            text-align:right;">{total}</td>
      </tr>
    </table>
  </td></tr>

  {tax_block}

  <tr><td style="padding:22px 28px 0;">
    <div style="font-size:13px;color:{_MUTED};">Сугалааны дугаар:
      <span style="color:{_INK};font-weight:700;font-family:'SFMono-Regular',Consolas,monospace;">
        {receipt.lottery or '-'}</span></div>
  </td></tr>

  <tr><td style="padding:16px 28px 30px;text-align:center;">
    <img src="cid:qr" width="190" height="190" alt="eBarimt QR"
         style="display:block;margin:0 auto;border:0;width:190px;height:190px;"/>
    <div style="font-size:11px;color:{_MUTED};padding-top:10px;">
      eBarimt аппаараа уншуулна уу</div>
  </td></tr>
</table>

<div style="font-size:11px;color:{_MUTED};padding:16px 8px 0;max-width:420px;
     font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
  Энэ бол автоматаар илгээсэн баримт — хариу бичих шаардлагагүй.
</div>
</td></tr></table></div>
</body></html>"""

    text_items = "\n".join(f"  {i['name']}  x{i['qty']}  {_money(i['total'])}" for i in items)
    text = f"""\
{greeting}

Нийт дүн: {total}

Төрөл : {_TYPE_LABEL.get(receipt.type, receipt.type or '-')}
ТТД   : {merchant_tin or '-'}
ДДТД  : {receipt.ebarimt_id or '-'}
Огноо : {date_str} {time_str}

{text_items}

Дүн   : {total}
Сугалааны дугаар: {receipt.lottery or '-'}

QR кодыг HTML хувилбараас үзнэ үү. Энэ бол автоматаар илгээсэн баримт.
"""

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = f"eBarimt төлбөрийн баримт — {total}"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    # Attach images into the HTML part so it becomes multipart/related and the
    # cid: references resolve. Attaching at top level instead leaves them as
    # separate downloads that the <img> tags can't reach in most clients.
    html_part = msg.get_payload()[-1]
    if logo:
        html_part.add_related(
            logo, maintype="image", subtype="png", cid="<logo>", filename="logo.png"
        )
    if receipt.qr_data:
        buf = io.BytesIO()
        segno.make(receipt.qr_data, error="m").save(buf, kind="png", scale=6, border=2)
        html_part.add_related(
            buf.getvalue(), maintype="image", subtype="png",
            cid="<qr>", filename="ebarimt-qr.png",
        )
    return msg
