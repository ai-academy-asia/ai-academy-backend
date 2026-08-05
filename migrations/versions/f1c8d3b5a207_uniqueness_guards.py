"""Database-level guards against double-sold seats and duplicate tax receipts

Both flows checked uniqueness with a plain SELECT and then inserted, which two
concurrent requests can both pass. The consequences are not recoverable by
retrying:

- two buyers pay for one seat;
- one payment gets two DDTDs from the tax authority, and PosAPI is not
  idempotent on voids either.

Partial indexes, because "taken" is a subset of rows: a released or cancelled
hold must not block the seat from being sold again.

Revision ID: f1c8d3b5a207
Revises: e4b1c72d9f08
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op

revision = "f1c8d3b5a207"
down_revision = "e4b1c72d9f08"
branch_labels = None
depends_on = None


def upgrade():
    # One live claim per seat. 'released'/'cancelled' rows are excluded so the
    # seat returns to the pool.
    op.create_index(
        "uq_seat_bookings_live_seat",
        "seat_bookings",
        ["cohort_id", "number_of_seat"],
        unique=True,
        postgresql_where=sa.text("status IN ('held', 'paid')"),
    )
    # One receipt per payment. Partial because payment_id is nullable.
    op.create_index(
        "uq_ebarimt_receipts_payment",
        "ebarimt_receipts",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_ebarimt_receipts_payment", table_name="ebarimt_receipts")
    op.drop_index("uq_seat_bookings_live_seat", table_name="seat_bookings")
