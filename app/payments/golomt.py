"""Golomt Bank *Corporate* account integration (statement reconciliation).

This is NOT a card/checkout gateway. Golomt Corporate exposes the company's own
bank account(s) over a host-to-host / cash-management API. There is no hosted
payment page: the student makes a bank transfer to our corporate account and
writes our reference in the transfer description. We then pull the account
statement and match incoming credits to open invoices.

Multiple receiving accounts (course routing)
-------------------------------------------
Finance may split collections across accounts by course. Example (director's rule)::

    MN930015003005201198  → "Online101" and "Summer bootcamp" fees
    MN820015003215155471  → every other class's fees (default)

Each :class:`GolomtAccount` carries the course identifiers it collects for; the
last one flagged ``default`` catches everything else. ``account_for`` resolves an
invoice's course to the right account at create time; ``reconcile`` pulls *every*
account's statement (a unique reference only appears under the correct one).

Flow
----
1. ``create_invoice`` — no external call. Picks the receiving account from the
   invoice's course and returns *payment instructions* (account + reference).
2. ``fetch_all_statements`` — pull credits for a date range from each account.
3. ``reconcile`` / ``check_invoice`` — match a statement credit to a pending
   invoice by reference (and amount) → settle it.

Config keys (``GOLOMT_CORP_*``)::

    GOLOMT_CORP_BASE_URL       corporate API base
    GOLOMT_CORP_TOKEN          static API token (if issued), else use client creds
    GOLOMT_CORP_CLIENT_ID      OAuth client id      (if token endpoint used)
    GOLOMT_CORP_CLIENT_SECRET  OAuth client secret
    GOLOMT_CORP_ACCOUNTS       JSON list of {account, name, courses[], default}
                               (preferred — multi-account routing)
    GOLOMT_CORP_ACCOUNT        single/default account (fallback if ACCOUNTS unset)
    GOLOMT_CORP_ACCOUNT_NAME   display name for the single/default account
    GOLOMT_CORP_TOKEN_PATH     default /v1/auth/token
    GOLOMT_CORP_STATEMENT_PATH default /v1/statement

WARNING: Golomt's corporate cash-management API is issued per-contract; the token
scheme, statement path, and field names below are best-effort defaults. Confirm
against the merchant's Golomt integration doc and adjust ``_normalize_txn`` +
the config paths — the reconciliation logic itself is provider-generic.
"""
from __future__ import annotations

from datetime import date, datetime

from .base import (
    InvoiceRequest,
    InvoiceResult,
    PaymentGatewayError,
    PaymentProvider,
    PaymentStatus,
    _TokenCache,
)
from .golomt_statement import (
    GolomtAccount,
    StatementTxn,
    _days,
    _norm,
    _parse_dt,
    _to_decimal,
)

_TOKENS = _TokenCache()


class GolomtCorporateProvider(PaymentProvider):
    name = "golomt"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = (config.get("base_url") or "").rstrip("/")
        self.static_token = config.get("token")
        self.client_id = config.get("client_id")
        self.client_secret = config.get("client_secret")
        self.token_path = config.get("token_path", "/v1/auth/token")
        self.statement_path = config.get("statement_path", "/v1/statement")
        self.accounts = self._build_accounts(config)
        self.default_account = next(
            (a for a in self.accounts if a.is_default), self.accounts[0] if self.accounts else None
        )

    @staticmethod
    def _build_accounts(config: dict) -> list[GolomtAccount]:
        """Prefer the multi-account ``accounts`` list; fall back to the single
        ``account``/``account_name`` pair (treated as the default)."""
        raw = config.get("accounts")
        accounts: list[GolomtAccount] = []
        if raw:
            for entry in raw:
                accounts.append(GolomtAccount(
                    number=entry["account"],
                    name=entry.get("name"),
                    courses=frozenset(_norm(c) for c in (entry.get("courses") or [])),
                    is_default=bool(entry.get("default")),
                ))
        elif config.get("account"):
            accounts.append(GolomtAccount(
                number=config["account"], name=config.get("account_name"), is_default=True))
        # Ensure exactly one default exists (last account catches the rest).
        if accounts and not any(a.is_default for a in accounts):
            accounts[-1].is_default = True
        return accounts

    def _require_config(self, *, need_api: bool = True):
        required = []
        if not self.accounts:
            required.append(("GOLOMT_CORP_ACCOUNT(S)", None))
        if need_api:
            required.append(("GOLOMT_CORP_BASE_URL", self.base_url))
            if not self.static_token:
                required.append(("GOLOMT_CORP_CLIENT_ID", self.client_id))
                required.append(("GOLOMT_CORP_CLIENT_SECRET", self.client_secret))
        missing = [k for k, v in required if not v]
        if missing:
            raise PaymentGatewayError(self.name, "not_configured", detail={"missing": missing})

    # ------------------------------------------------------------- routing
    def account_for(self, *identifiers) -> GolomtAccount:
        """Pick the receiving account for a course (by slug/title). Falls back to
        the default account when no course-specific rule matches."""
        for acc in self.accounts:
            if not acc.is_default and acc.collects(*identifiers):
                return acc
        return self.default_account

    def _account_by_number(self, number) -> GolomtAccount | None:
        return next((a for a in self.accounts if a.number == number), None)

    # ---------------------------------------------------------------- auth
    def _token(self) -> str:
        if self.static_token:
            return self.static_token
        cached = _TOKENS.get()
        if cached:
            return cached
        data = self._request(
            "POST", f"{self.base_url}{self.token_path}",
            json={"clientId": self.client_id, "clientSecret": self.client_secret},
        )
        token = data.get("access_token") or data.get("token")
        if not token:
            raise PaymentGatewayError(self.name, "auth_failed", detail=data)
        _TOKENS.set(token, float(data.get("expires_in", 3600)))
        return token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    # ------------------------------------------------------------- invoice
    def create_invoice(self, req: InvoiceRequest) -> InvoiceResult:
        """No gateway call — return the transfer instructions the payer follows.

        The receiving account is chosen from the course hints in ``req.extra``
        (``course_slug`` / ``course_title``). The payer must include
        ``sender_invoice_no`` in the transfer description so ``reconcile`` can
        later link their credit to this invoice.
        """
        self._require_config(need_api=False)
        acc = self.account_for(req.extra.get("course_slug"), req.extra.get("course_title"))
        if acc is None:
            raise PaymentGatewayError(self.name, "no_receiving_account")
        instructions = {
            "type": "bank_transfer",
            "bank": "Golomt Bank",
            "account_number": acc.number,
            "account_name": acc.name,
            "amount": float(req.amount),
            "currency": req.currency,
            "reference": req.sender_invoice_no,
            "routed_by_course": req.extra.get("course_slug") or req.extra.get("course_title"),
            "instructions_mn": (
                f"Голомт банкны {acc.number} дансанд {float(req.amount):,.0f}{req.currency} "
                f"шилжүүлж, гүйлгээний утга дээр {req.sender_invoice_no} гэж бичнэ үү."
            ),
        }
        # provider_invoice_id == our reference; account_number lives in raw/provider_meta.
        return InvoiceResult(provider_invoice_id=req.sender_invoice_no, raw=instructions)

    # ----------------------------------------------------------- statement
    def fetch_statement(self, from_date: date, to_date: date, account: str) -> list[StatementTxn]:
        self._require_config(need_api=True)
        data = self._request(
            "GET", f"{self.base_url}{self.statement_path}",
            params={"account": account, "from": from_date.isoformat(), "to": to_date.isoformat()},
            headers=self._auth_headers(),
        )
        rows = data.get("transactions") or data.get("rows") or data.get("data") or []
        txns = []
        for row in rows:
            txn = self._normalize_txn(row, account)
            if txn is not None:
                txns.append(txn)
        return txns

    def fetch_all_statements(self, from_date: date, to_date: date) -> list[StatementTxn]:
        """Pull and combine credits across every configured receiving account."""
        self._require_config(need_api=True)
        all_txns: list[StatementTxn] = []
        for acc in self.accounts:
            all_txns.extend(self.fetch_statement(from_date, to_date, acc.number))
        return all_txns

    def _normalize_txn(self, row: dict, account: str | None = None) -> StatementTxn | None:
        """Map a raw statement row → StatementTxn, keeping only credits (money in).

        Adjust the field names here to match the merchant's Golomt statement
        schema. Debits (money out) are skipped.
        """
        amount = _to_decimal(
            row.get("creditAmount") or row.get("amount") or row.get("txnAmount")
        )
        if amount is None or amount <= 0:
            return None
        # Skip explicit debits when a direction flag is present.
        direction = str(row.get("drCr") or row.get("type") or row.get("direction") or "").upper()
        if direction in ("DR", "DEBIT", "D"):
            return None
        return StatementTxn(
            txn_id=str(row.get("txnId") or row.get("id") or row.get("transactionId") or ""),
            amount=amount,
            description=str(
                row.get("description") or row.get("narrative") or row.get("memo") or ""),
            account=account or row.get("account"),
            posted_at=_parse_dt(row.get("postedAt") or row.get("date") or row.get("txnDate")),
            counterparty=row.get("counterparty") or row.get("senderName"),
            raw=row,
        )

    # -------------------------------------------------------------- status
    def check_invoice(self, invoice) -> PaymentStatus:
        """Match this single invoice against recent statement credits.

        Looks only at the account this invoice was routed to (recorded in
        ``provider_meta.account_number``), falling back to all accounts.
        """
        window_days = int(self.config.get("match_window_days", 14))
        to_d = datetime.utcnow().date()
        from_d = to_d - _days(window_days)

        meta = invoice.provider_meta or {}
        acc = self._account_by_number(meta.get("account_number"))
        txns = (
            self.fetch_statement(from_d, to_d, acc.number) if acc
            else self.fetch_all_statements(from_d, to_d)
        )
        for txn in txns:
            if self.matches(invoice, txn):
                return PaymentStatus(
                    paid=True,
                    provider_payment_id=txn.txn_id or invoice.sender_invoice_no,
                    amount=txn.amount,
                    paid_at=txn.posted_at,
                    method="transfer",
                    raw=txn.raw,
                )
        return PaymentStatus.unpaid()

    def verify_callback(self, invoice, payload, headers):
        # Golomt corporate has no per-payment webhook; reconciliation is pull-based.
        return self.check_invoice(invoice)

    @staticmethod
    def matches(invoice, txn: StatementTxn) -> bool:
        """A statement credit settles an invoice when its description carries our
        reference AND the amount matches (exact, to the cent)."""
        ref = (invoice.sender_invoice_no or "").lower()
        if not ref or ref not in (txn.description or "").lower():
            return False
        return _to_decimal(invoice.amount) == txn.amount
