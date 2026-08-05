"""Public (unauthenticated) enrolment funnel — lead, seat hold, promotion.

The marketing site has no user accounts: a visitor browses programmes, fills a
form and pays, all anonymously. That flow needs three things the authenticated
LMS models don't provide:

- a **lead** row that exists before anyone is a student (:class:`ClassroomRequest`),
- a **held** seat that is neither free nor sold (:class:`SeatBooking`), and
- an opaque **payment token** that keys the rest of the flow, because there is
  no session to authorize against.

Naming follows the front-end contract (``docs/enrolment-api.md`` in the web
repo) rather than our internal vocabulary, so the JSON needs no translation
layer: their *classroom course* is our :class:`~app.models.course.Course`, their
*schedule* is our :class:`~app.models.cohort.Cohort`.
"""
import secrets
from datetime import datetime, timedelta

from app.extensions import db

REQUEST_STATUSES = ("new", "booked", "paid", "abandoned")
# held  — seat reserved, no money yet (expires)
# paid  — settled; the seat is sold
# released / cancelled — hold expired or abandoned; the seat is free again
BOOKING_STATUSES = ("held", "paid", "released", "cancelled")
DISCOUNT_TYPES = ("percent", "amount")

# How long a seat stays held before the sweeper frees it.
DEFAULT_HOLD_MINUTES = 30


def new_payment_token() -> str:
    """Opaque, unguessable handle for one checkout.

    This is the *only* credential the public payment endpoints have — anyone
    holding it can read the invoice, its status and the receipt — so it must be
    random, not derived from a row id.
    """
    return f"pt_{secrets.token_urlsafe(24)}"


class ClassroomRequest(db.Model):
    """A sales lead: someone submitted the enrolment form.

    Created before payment and kept even when payment never happens — the sales
    team works these. ``status`` is what separates a real enrolment from an
    abandoned one.
    """

    __tablename__ = "classroom_requests"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )

    name = db.Column(db.String(200), nullable=False)      # "<last> <first>", as typed
    email = db.Column(db.String(255), nullable=False, index=True)
    phone_num = db.Column(db.String(20), nullable=False)
    phone_num2 = db.Column(db.String(20))
    # Personal data, sent unauthenticated: the receipt is issued against it.
    # Never log it; it is returned to nobody.
    register_num = db.Column(db.String(20))
    # Free-text sales summary built by the front-end. Stored verbatim, never parsed.
    student_plan = db.Column(db.Text)

    status = db.Column(db.String(20), nullable=False, default="new", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    bookings = db.relationship("SeatBooking", back_populates="request")

    def to_dict(self) -> dict:
        """The contract returns only the id — the front-end just passes it back."""
        return {"_id": self.id}

    def __repr__(self) -> str:
        return f"<ClassroomRequest {self.id} course={self.course_id} {self.status}>"


class SeatBooking(db.Model):
    """One held-or-sold seat on a cohort, and the payment token for its checkout."""

    __tablename__ = "seat_bookings"
    __table_args__ = (
        db.Index("ix_seat_bookings_cohort_status", "cohort_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    classroom_request_id = db.Column(
        db.Integer, db.ForeignKey("classroom_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cohort_id = db.Column(
        db.Integer, db.ForeignKey("cohorts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    number_of_seat = db.Column(db.Integer, nullable=False)

    payment_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="held", index=True)

    # Discount captured at booking time, so the charged amount stays reproducible
    # even if the promotion is edited or expires afterwards.
    promotion_code = db.Column(db.String(60))
    promotion_name = db.Column(db.String(200))
    promotion_amount = db.Column(db.Numeric(12, 2))

    # Amount the server derived for this booking. The client may send a figure;
    # it is advisory — this is what gets charged.
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="MNT")

    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    expires_at = db.Column(db.DateTime, index=True)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    request = db.relationship("ClassroomRequest", back_populates="bookings")
    cohort = db.relationship("Cohort")
    invoice = db.relationship("Invoice")

    @staticmethod
    def default_expiry(minutes: int = DEFAULT_HOLD_MINUTES) -> datetime:
        return datetime.utcnow() + timedelta(minutes=minutes)

    @property
    def is_expired(self) -> bool:
        return (
            self.status == "held"
            and self.expires_at is not None
            and self.expires_at < datetime.utcnow()
        )

    def to_dict(self) -> dict:
        return {"payment_token": self.payment_token}

    def __repr__(self) -> str:
        return (f"<SeatBooking {self.id} cohort={self.cohort_id} "
                f"seat={self.number_of_seat} {self.status}>")


class Promotion(db.Model):
    """A promo code the public form can apply.

    Kept as a table rather than config so codes can expire and be added without
    a deploy — the endpoint's whole job is 404-vs-200 on an unknown code.
    """

    __tablename__ = "promotions"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)      # shown to the buyer
    discount_type = db.Column(db.String(10), nullable=False, default="percent")
    discount_value = db.Column(db.Numeric(12, 2), nullable=False)

    # Optional scoping: NULL course_id = valid on everything.
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    starts_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    max_uses = db.Column(db.Integer)
    used_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def is_valid_now(self, course_id=None) -> bool:
        now = datetime.utcnow()
        if not self.is_active:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.expires_at and self.expires_at < now:
            return False
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False
        return self.course_id in (None, course_id)

    def to_dict(self) -> dict:
        """Exactly the contract's Coupon shape."""
        return {
            "name": self.name,
            "discount_type": self.discount_type,
            "discount_value": float(self.discount_value),
        }

    def __repr__(self) -> str:
        return f"<Promotion {self.code} {self.discount_type}={self.discount_value}>"
