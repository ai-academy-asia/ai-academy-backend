"""Enrollment price snapshot + per-course installment rule

Revision ID: 8e4a1c6f2d90
Revises: 7d3f2b9e5a14
Create Date: 2026-10-22

Backfills every enrollment with its course's current discounted price (the best
record we have of what was quoted) and rebuilds ``total_due`` / ``balance`` on
existing ledgers under the new rule: Σ non-waived installments when a plan
exists, else the enrollment's price — never "whatever was paid".
"""
import sqlalchemy as sa
from alembic import op

revision = "8e4a1c6f2d90"
down_revision = "7d3f2b9e5a14"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enrollments", sa.Column("price_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("enrollments", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("courses", sa.Column(
        "installment_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("courses", sa.Column(
        "installment_interval_months", sa.Integer(), nullable=False, server_default="1"))

    op.execute("""
        UPDATE enrollments e
           SET price_amount = round(coalesce(c.price_amount, 0)
                                    * (100 - coalesce(c.discount_percent, 0)) / 100, 2),
               currency = coalesce(c.currency, 'MNT')
          FROM courses c
         WHERE c.id = e.course_id AND e.price_amount IS NULL
    """)
    op.execute("""
        UPDATE student_ledger l
           SET total_due = CASE
               WHEN EXISTS (SELECT 1 FROM payment_installments i
                             WHERE i.enrollment_id = l.enrollment_id)
               THEN (SELECT coalesce(sum(i.amount), 0) FROM payment_installments i
                      WHERE i.enrollment_id = l.enrollment_id AND i.status <> 'waived')
               ELSE coalesce((SELECT e.price_amount FROM enrollments e
                               WHERE e.id = l.enrollment_id), 0)
           END
    """)
    op.execute("UPDATE student_ledger SET balance = total_due - total_paid")


def downgrade():
    op.drop_column("courses", "installment_interval_months")
    op.drop_column("courses", "installment_count")
    op.drop_column("enrollments", "currency")
    op.drop_column("enrollments", "price_amount")
