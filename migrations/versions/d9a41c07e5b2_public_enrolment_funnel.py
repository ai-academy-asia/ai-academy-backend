"""Public enrolment funnel: leads, seat holds, promotions + receipt delivery state

Adds the tables the unauthenticated marketing-site flow needs (a lead that
exists before anyone is a student, a seat that is held rather than sold, and a
promo code), plus the columns that let /payments/receipt report whether the
и-баримт actually reached the buyer.

Revision ID: d9a41c07e5b2
Revises: c3d5a8f21b6e
Create Date: 2026-08-05

"""
import sqlalchemy as sa
from alembic import op

revision = "d9a41c07e5b2"
down_revision = "c3d5a8f21b6e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "classroom_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone_num", sa.String(length=20), nullable=False),
        sa.Column("phone_num2", sa.String(length=20), nullable=True),
        sa.Column("register_num", sa.String(length=20), nullable=True),
        sa.Column("student_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classroom_requests_course_id", "classroom_requests",
                    ["course_id"])
    op.create_index("ix_classroom_requests_email", "classroom_requests", ["email"])
    op.create_index("ix_classroom_requests_status", "classroom_requests", ["status"])

    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("discount_type", sa.String(length=10), nullable=False,
                  server_default="percent"),
        sa.Column("discount_value", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_promotions_code", "promotions", ["code"])
    op.create_index("ix_promotions_course_id", "promotions", ["course_id"])
    op.create_index("ix_promotions_is_active", "promotions", ["is_active"])

    op.create_table(
        "seat_bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("classroom_request_id", sa.Integer(), nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("number_of_seat", sa.Integer(), nullable=False),
        sa.Column("payment_token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="held"),
        sa.Column("promotion_code", sa.String(length=60), nullable=True),
        sa.Column("promotion_name", sa.String(length=200), nullable=True),
        sa.Column("promotion_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False,
                  server_default="MNT"),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["classroom_request_id"], ["classroom_requests.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_token"),
    )
    op.create_index("ix_seat_bookings_classroom_request_id", "seat_bookings",
                    ["classroom_request_id"])
    op.create_index("ix_seat_bookings_cohort_id", "seat_bookings", ["cohort_id"])
    op.create_index("ix_seat_bookings_payment_token", "seat_bookings",
                    ["payment_token"])
    op.create_index("ix_seat_bookings_status", "seat_bookings", ["status"])
    op.create_index("ix_seat_bookings_invoice_id", "seat_bookings", ["invoice_id"])
    op.create_index("ix_seat_bookings_expires_at", "seat_bookings", ["expires_at"])
    op.create_index("ix_seat_bookings_cohort_status", "seat_bookings",
                    ["cohort_id", "status"])

    # Delivery state is separate from tax state: a receipt can be validly issued
    # and still not have reached the buyer.
    op.add_column("ebarimt_receipts", sa.Column("emailed_at", sa.DateTime(), nullable=True))
    op.add_column("ebarimt_receipts",
                  sa.Column("emailed_to", sa.String(length=255), nullable=True))
    op.add_column("ebarimt_receipts",
                  sa.Column("email_error", sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column("ebarimt_receipts", "email_error")
    op.drop_column("ebarimt_receipts", "emailed_to")
    op.drop_column("ebarimt_receipts", "emailed_at")

    op.drop_index("ix_seat_bookings_cohort_status", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_expires_at", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_invoice_id", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_status", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_payment_token", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_cohort_id", table_name="seat_bookings")
    op.drop_index("ix_seat_bookings_classroom_request_id", table_name="seat_bookings")
    op.drop_table("seat_bookings")

    op.drop_index("ix_promotions_is_active", table_name="promotions")
    op.drop_index("ix_promotions_course_id", table_name="promotions")
    op.drop_index("ix_promotions_code", table_name="promotions")
    op.drop_table("promotions")

    op.drop_index("ix_classroom_requests_status", table_name="classroom_requests")
    op.drop_index("ix_classroom_requests_email", table_name="classroom_requests")
    op.drop_index("ix_classroom_requests_course_id", table_name="classroom_requests")
    op.drop_table("classroom_requests")
