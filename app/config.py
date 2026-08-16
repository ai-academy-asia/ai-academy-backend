import json
import os


def _parse_json_env(name: str):
    """Parse a JSON env var into a Python value; return None if unset/blank.

    Malformed JSON aborts the boot rather than falling back to ``None``: for
    GOLOMT_CORP_ACCOUNTS a silent ``None`` doesn't disable the feature, it routes
    every course fee into the single-account fallback — misrouted money that only
    surfaces at reconciliation. A config typo is cheapest to fix at startup.
    """
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON: {exc}") from exc


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var (true/1/yes/on). Falls back to ``default`` if unset."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _build_database_url() -> str:
    """Return DATABASE_URL if set, otherwise assemble it from POSTGRES_* parts."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "aiaa")
    password = os.getenv("POSTGRES_PASSWORD", "aiaa_dev_password")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "aiaa")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = _build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Auth / JWT ---
    # Falls back to SECRET_KEY if JWT_SECRET is not set separately.
    JWT_SECRET = os.getenv("JWT_SECRET") or SECRET_KEY
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    # Access-token lifetime in seconds. Kept short (1h) because refresh tokens
    # exist — a long-lived stateless access token would undermine the shorter
    # staff refresh window.
    JWT_ACCESS_TTL = int(os.getenv("JWT_ACCESS_TTL", str(60 * 60)))

    # --- Refresh tokens (DB-backed, opaque, rotated) ---
    # Learners (student/teacher) get a long refresh window; staff get a short
    # one because they can act on money data. Sliding window (each rotate resets
    # the clock). All in seconds.
    REFRESH_TTL_STUDENT = int(os.getenv("REFRESH_TTL_STUDENT", str(30 * 24 * 60 * 60)))
    REFRESH_TTL_TEACHER = int(os.getenv("REFRESH_TTL_TEACHER", str(30 * 24 * 60 * 60)))
    REFRESH_TTL_STAFF = int(os.getenv("REFRESH_TTL_STAFF", str(12 * 60 * 60)))

    # Minimum length enforced on password changes.
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))

    # --- S3 (cert / contract template files) ---
    # boto3 uses its default credential chain (env keys, shared profile, or the
    # EC2 instance role in prod). Only the bucket/region need configuring here.
    AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
    S3_BUCKET = os.getenv("S3_BUCKET", "aiaa-templates-748560966884")
    S3_PREFIX = os.getenv("S3_PREFIX", "")  # optional key prefix
    # Max upload size for a template file (bytes). Default 15 MB.
    MAX_TEMPLATE_BYTES = int(os.getenv("MAX_TEMPLATE_BYTES", str(15 * 1024 * 1024)))

    # Rate used to store the catalogue's USD-quoted courses in MNT. Everything
    # downstream — QPay, the ledger, the eBarimt receipt — is MNT-only, so a USD
    # price is unsellable (enrolment answers 409 price_not_in_mnt). Seeding
    # converts once, at this rate, rather than leaving the figure to be guessed
    # at checkout. Move it when the pricing does, then re-run `flask seed courses`.
    USD_MNT_RATE = os.getenv("USD_MNT_RATE", "3600")

    # --- Payments ---
    # Public origin used to build gateway callback URLs (must be reachable by the
    # provider's servers). Defaults to the live API host.
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://api.ai-academy.asia")
    PAYMENT_HTTP_TIMEOUT = int(os.getenv("PAYMENT_HTTP_TIMEOUT", "20"))
    # Demo/QA switch: settle every checkout instantly, with no gateway and no
    # money, so the rest of the flow (seat, ledger, eBarimt receipt) can be
    # exercised while merchant credentials are pending. NEVER in production —
    # create_app refuses to start with it on against the live API host.
    PAYMENTS_SANDBOX = _env_bool("PAYMENTS_SANDBOX", False)

    # QPay v2 (QR / bank deeplink).
    QPAY_BASE_URL = os.getenv("QPAY_BASE_URL", "https://merchant.qpay.mn")
    QPAY_USERNAME = os.getenv("QPAY_USERNAME")
    QPAY_PASSWORD = os.getenv("QPAY_PASSWORD")
    QPAY_INVOICE_CODE = os.getenv("QPAY_INVOICE_CODE")

    # StorePay (buy-now-pay-later / loan). Endpoint paths overridable per contract.
    STOREPAY_BASE_URL = os.getenv("STOREPAY_BASE_URL", "https://service.storepay.mn")
    STOREPAY_AUTH_URL = os.getenv("STOREPAY_AUTH_URL")  # defaults to STOREPAY_BASE_URL
    STOREPAY_CLIENT_ID = os.getenv("STOREPAY_CLIENT_ID")
    STOREPAY_CLIENT_SECRET = os.getenv("STOREPAY_CLIENT_SECRET")
    STOREPAY_USERNAME = os.getenv("STOREPAY_USERNAME")
    STOREPAY_PASSWORD = os.getenv("STOREPAY_PASSWORD")
    STOREPAY_STORE_ID = os.getenv("STOREPAY_STORE_ID")
    STOREPAY_TOKEN_PATH = os.getenv("STOREPAY_TOKEN_PATH", "/oauth/token")
    STOREPAY_LOAN_PATH = os.getenv("STOREPAY_LOAN_PATH", "/merchant/loan")
    STOREPAY_DETAILS_PATH = os.getenv("STOREPAY_DETAILS_PATH", "/merchant/loan/details")

    # Golomt Corporate (bank-transfer statement reconciliation, not a card gateway).
    GOLOMT_CORP_BASE_URL = os.getenv("GOLOMT_CORP_BASE_URL")
    GOLOMT_CORP_TOKEN = os.getenv("GOLOMT_CORP_TOKEN")
    GOLOMT_CORP_CLIENT_ID = os.getenv("GOLOMT_CORP_CLIENT_ID")
    GOLOMT_CORP_CLIENT_SECRET = os.getenv("GOLOMT_CORP_CLIENT_SECRET")
    # Multi-account routing: JSON list of {account, name, courses[], default}.
    # Fees for the listed courses land in that account; the account flagged
    # "default" (or, if none, the last one) collects everything else.
    GOLOMT_CORP_ACCOUNTS = _parse_json_env("GOLOMT_CORP_ACCOUNTS")
    # Single/default account fallback (used only when GOLOMT_CORP_ACCOUNTS is unset).
    GOLOMT_CORP_ACCOUNT = os.getenv("GOLOMT_CORP_ACCOUNT")
    GOLOMT_CORP_ACCOUNT_NAME = os.getenv("GOLOMT_CORP_ACCOUNT_NAME", "AI Academy Asia")
    GOLOMT_CORP_TOKEN_PATH = os.getenv("GOLOMT_CORP_TOKEN_PATH", "/v1/auth/token")
    GOLOMT_CORP_STATEMENT_PATH = os.getenv("GOLOMT_CORP_STATEMENT_PATH", "/v1/statement")
    GOLOMT_CORP_MATCH_WINDOW_DAYS = int(os.getenv("GOLOMT_CORP_MATCH_WINDOW_DAYS", "14"))

    # --- eBarimt (Mongolian e-receipt, via local PosAPI) ---
    # Temp mode: run without real PosAPI merchant rights — receipts are stored
    # locally (is_temp_mode=True) and replayed to the real PosAPI once live.
    EBARIMT_TEMP_MODE = _env_bool("EBARIMT_TEMP_MODE", True)
    EBARIMT_AUTO_ISSUE = _env_bool("EBARIMT_AUTO_ISSUE", True)  # issue on payment settle
    EBARIMT_POSAPI_URL = os.getenv("EBARIMT_POSAPI_URL", "http://localhost:7080")
    EBARIMT_HTTP_TIMEOUT = int(os.getenv("EBARIMT_HTTP_TIMEOUT", "15"))
    EBARIMT_RECEIPT_PATH = os.getenv("EBARIMT_RECEIPT_PATH", "/rest/receipt")
    EBARIMT_INFO_PATH = os.getenv("EBARIMT_INFO_PATH", "/rest/info")
    EBARIMT_SEND_DATA_PATH = os.getenv("EBARIMT_SEND_DATA_PATH", "/rest/sendData")
    # Public taxpayer directory — confirms a company name from its TIN before a
    # B2B receipt is filed. Cloud, not the local PosAPI; staging lives at
    # https://st-api.ebarimt.mn.
    EBARIMT_INFO_API_URL = os.getenv("EBARIMT_INFO_API_URL", "https://api.ebarimt.mn")
    # Merchant/receipt attributes (from PosAPI /rest/info + /web merchant registration).
    # merchantTin MUST already be registered in PosAPI's merchant list (via :7080/web) —
    # PosAPI rejects any TIN it doesn't recognize, even the operator's own TIN.
    EBARIMT_MERCHANT_TIN = os.getenv("EBARIMT_MERCHANT_TIN")
    # Shown as the seller on the receipt body / email header.
    MERCHANT_NAME = os.getenv("MERCHANT_NAME", "AI ACADEMY ASIA")
    EBARIMT_BRANCH_NO = os.getenv("EBARIMT_BRANCH_NO", "")
    EBARIMT_DISTRICT_CODE = os.getenv("EBARIMT_DISTRICT_CODE", "")
    EBARIMT_POS_NO = os.getenv("EBARIMT_POS_NO")
    # ҮАБТ ангиллын код for what we actually sell: 9291900 "Боловсролын бусад
    # төрлийн сургалтын үйлчилгээ". The old 6851000 was a courier/post service —
    # wrong line of business on every receipt issued under it.
    EBARIMT_CLASSIFICATION_CODE = os.getenv("EBARIMT_CLASSIFICATION_CODE", "9291900")
    EBARIMT_TAX_PRODUCT_CODE = os.getenv("EBARIMT_TAX_PRODUCT_CODE", "")
    # Tax handling. VAT 10% is included in the price by default; set false if the
    # service is VAT-exempt. City tax rate (%) on the net; 0 for tuition.
    EBARIMT_VAT_INCLUDED = _env_bool("EBARIMT_VAT_INCLUDED", True)
    EBARIMT_CITY_TAX_RATE = os.getenv("EBARIMT_CITY_TAX_RATE", "0")
    # Email the issued receipt to the student. Only fires for real (non-temp)
    # receipts — a temp one has no DDTD/QR, so there is nothing to show.
    EBARIMT_EMAIL_RECEIPT = _env_bool("EBARIMT_EMAIL_RECEIPT", True)

    # ---- Outbound email (SMTP) ----
    # Unset MAIL_HOST disables sending entirely: receipts are still issued and
    # stored, the delivery step is just skipped and logged.
    MAIL_HOST = os.getenv("MAIL_HOST")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)    # STARTTLS, port 587
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)   # implicit TLS, port 465
    MAIL_FROM = os.getenv("MAIL_FROM", "AI Academy Asia <no-reply@ai-academy.asia>")
    MAIL_REPLY_TO = os.getenv("MAIL_REPLY_TO", "")
    MAIL_TIMEOUT = int(os.getenv("MAIL_TIMEOUT", "20"))
    # Override the receipt-email logo. Unset -> app/mail/ uses its own bundled
    # asset; that package owns the file layout, config only carries the override.
    RECEIPT_LOGO_PATH = os.getenv("RECEIPT_LOGO_PATH")
