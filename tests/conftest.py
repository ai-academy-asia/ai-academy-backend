"""Shared pytest harness.

Every test runs the real app against a real PostgreSQL database — the schema
leans on Postgres (JSON, Numeric, ON DELETE rules), so SQLite would test a
different program. Nothing leaves the machine: outbound HTTP and SMTP are
blocked, and tests that need a gateway, PosAPI or S3 stub it explicitly.

Point it at a database with ``TEST_DATABASE_URL`` (default: the local Docker
Postgres, database ``aiaa_test``). The database is wiped between tests, so the
guard below refuses anything that is not a local ``*_test`` database — ``.env``
points at the production RDS, and one stray export must not be able to empty it.
"""
import os
from urllib.parse import urlparse

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://aiaa_admin:aiaa_dev_password@localhost:5433/aiaa_test",
)


def _assert_disposable(url: str) -> None:
    parsed = urlparse(url.replace("postgresql+psycopg2", "postgresql"))
    host = (parsed.hostname or "").lower()
    name = parsed.path.lstrip("/")
    if host not in ("localhost", "127.0.0.1", "db", "postgres") or not name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run tests against {host}/{name}: the suite truncates every "
            "table. Use a local database whose name ends in _test."
        )


_assert_disposable(TEST_DATABASE_URL)
# Config reads the environment at import time, so this must precede `import app`.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.pop("DB_SECRET_ARN", None)

import pytest  # noqa: E402
import requests  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.auth import create_access_token  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import db as _db  # noqa: E402


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    DB_SECRET_ARN = None
    SECRET_KEY = "test-secret"
    JWT_SECRET = "test-secret"
    PUBLIC_BASE_URL = "http://testserver"
    PAYMENTS_SANDBOX = False

    QPAY_USERNAME = "test"
    QPAY_PASSWORD = "test"
    QPAY_INVOICE_CODE = "TEST_INVOICE"
    STOREPAY_CLIENT_ID = STOREPAY_CLIENT_SECRET = None
    GOLOMT_CORP_BASE_URL = None
    GOLOMT_CORP_ACCOUNTS = None
    GOLOMT_CORP_ACCOUNT = "1234567890"

    EBARIMT_TEMP_MODE = True
    EBARIMT_AUTO_ISSUE = True
    EBARIMT_POSAPI_URL = "http://posapi.invalid"
    EBARIMT_INFO_API_URL = "http://ebarimt-info.invalid"
    EBARIMT_MERCHANT_TIN = "TEST_TIN"
    EBARIMT_POS_NO = "TEST_POS"
    EBARIMT_DISTRICT_CODE = "3501"
    EBARIMT_EMAIL_RECEIPT = True

    MAIL_HOST = None  # sending disabled unless a test stubs the transport
    S3_BUCKET = "test-bucket"


@pytest.fixture(scope="session")
def app():
    from flask_migrate import upgrade

    app = create_app(TestConfig)
    with app.app_context():
        # Build the schema from the migrations, not create_all(): the partial
        # unique indexes guarding seats and receipts exist only there.
        _db.session.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        _db.session.commit()
        upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
        yield app
        _db.session.remove()


@pytest.fixture(autouse=True)
def _clean_db(app):
    """Empty every table after each test so tests never see each other's rows."""
    yield
    _db.session.rollback()
    _db.session.remove()
    tables = ", ".join(f'"{t.name}"' for t in _db.metadata.sorted_tables)
    _db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    _db.session.commit()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly on any real outbound call a test forgot to stub."""

    def _blocked(self, method, url, *args, **kwargs):
        raise AssertionError(f"unexpected outbound HTTP in test: {method} {url}")

    def _blocked_smtp(*args, **kwargs):
        raise AssertionError("unexpected outbound SMTP in test")

    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)
    monkeypatch.setattr("smtplib.SMTP", _blocked_smtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", _blocked_smtp)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


# ----------------------------------------------------------------- actors
PASSWORD = "Passw0rd!"


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account)}"}


@pytest.fixture
def make_staff(app):
    """``make_staff(role="finance")`` -> (account, auth headers)."""
    from app.auth.service import create_staff_account

    counter = {"n": 0}

    def _make(role="super_admin", email=None, **kwargs):
        counter["n"] += 1
        account, _ = create_staff_account(
            email=email or f"{role}{counter['n']}@staff.test", password=PASSWORD,
            first_name=role.title(), role=role, must_change_password=False, **kwargs,
        )
        return account, _headers(account)

    return _make


@pytest.fixture
def make_student(app):
    """``make_student()`` -> (account, auth headers). ``account.actor_id`` is the student id."""
    from app.auth.service import create_student_account

    counter = {"n": 0}

    def _make(email=None, first_name="Bat", **kwargs):
        counter["n"] += 1
        account, _ = create_student_account(
            email=email or f"student{counter['n']}@student.test", password=PASSWORD,
            first_name=first_name, must_change_password=False, **kwargs,
        )
        return account, _headers(account)

    return _make


@pytest.fixture
def make_teacher(app):
    """``make_teacher()`` -> (account, auth headers). ``account.actor_id`` is the teacher id."""
    from app.auth.service import create_teacher_account

    counter = {"n": 0}

    def _make(email=None, first_name="Dorj", **kwargs):
        counter["n"] += 1
        account, _ = create_teacher_account(
            email=email or f"teacher{counter['n']}@teacher.test", password=PASSWORD,
            first_name=first_name, must_change_password=False, **kwargs,
        )
        return account, _headers(account)

    return _make


@pytest.fixture
def admin_headers(make_staff):
    return make_staff("super_admin")[1]


# ----------------------------------------------------------------- domain rows
@pytest.fixture
def make_course(db):
    from app.models import Course

    counter = {"n": 0}

    def _make(**fields):
        counter["n"] += 1
        values = {
            "slug": f"course-{counter['n']}", "title_mn": f"Хөтөлбөр {counter['n']}",
            "status": "open", "price_amount": 1_000_000, "currency": "MNT",
        }
        values.update(fields)
        course = Course(**values)
        db.session.add(course)
        db.session.commit()
        return course

    return _make


@pytest.fixture
def make_classroom(db):
    from app.models import Classroom

    counter = {"n": 0}

    def _make(**fields):
        counter["n"] += 1
        values = {"name": f"Room {counter['n']}", "center_name": "Central", "capacity": 20}
        values.update(fields)
        room = Classroom(**values)
        db.session.add(room)
        db.session.commit()
        return room

    return _make


@pytest.fixture
def make_cohort(db, make_course):
    from datetime import date

    from app.models import Cohort

    counter = {"n": 0}

    def _make(course=None, **fields):
        counter["n"] += 1
        course = course or make_course()
        values = {
            "course_id": course.id, "name": f"Cohort {counter['n']}", "status": "open",
            "start_date": date(2026, 10, 1), "end_date": date(2026, 12, 1), "capacity": 10,
        }
        values.update(fields)
        cohort = Cohort(**values)
        db.session.add(cohort)
        db.session.commit()
        return cohort

    return _make


# ----------------------------------------------------------------- gateway stub
class FakeProvider:
    """Stands in for QPay / StorePay / Golomt. Tests flip ``paid`` / ``fail``."""

    def __init__(self, name):
        from decimal import Decimal

        self.name = name
        self.paid = False
        self.fail = None          # a PaymentGatewayError to raise, or None
        self.amount = None        # override the settled amount (default: invoice amount)
        self.created = []
        self.statement = []       # rows returned by Golomt reconcile, if asked
        self._Decimal = Decimal

    def create_invoice(self, req):
        from app.payments import InvoiceResult

        if self.fail:
            raise self.fail
        self.created.append(req)
        return InvoiceResult(
            provider_invoice_id=f"{self.name.upper()}-{req.sender_invoice_no}",
            qr_text=f"QR|{req.sender_invoice_no}", qr_image="aW1n",
            payment_url=f"https://pay.test/{req.sender_invoice_no}", urls=[],
            raw={"fake": True},
        )

    def check_invoice(self, invoice):
        from datetime import datetime

        from app.payments import PaymentStatus

        if self.fail:
            raise self.fail
        if not self.paid:
            return PaymentStatus.unpaid()
        amount = self.amount if self.amount is not None else invoice.amount
        return PaymentStatus(
            paid=True, provider_payment_id=f"TXN-{invoice.id}",
            amount=self._Decimal(str(amount)), paid_at=datetime.utcnow(), method="qr",
            raw={"fake": True},
        )

    def verify_callback(self, invoice, payload, headers):
        return self.check_invoice(invoice)

    def __getattr__(self, item):
        raise AttributeError(f"FakeProvider({self.name}) has no {item!r}; stub it in the test")


@pytest.fixture
def gateways(monkeypatch):
    """Replace every real gateway with a :class:`FakeProvider`.

    ``gateways["qpay"].paid = True`` makes the next check/callback settle.
    """
    from app.payments import PaymentGatewayError

    fakes = {name: FakeProvider(name) for name in ("qpay", "storepay", "golomt")}

    def _get(name):
        if name not in fakes:
            raise PaymentGatewayError(name or "unknown", "unsupported_provider")
        return fakes[name]

    monkeypatch.setattr("app.services.payments.get_provider", _get)
    return fakes
