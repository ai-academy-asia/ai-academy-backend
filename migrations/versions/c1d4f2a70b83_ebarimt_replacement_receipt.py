"""Let a payment carry a replacement receipt after a partial refund

eBarimt cannot void half a receipt: a partial refund returns the original whole
and issues a second receipt for what the buyer kept. Without the link the pair
reads as two unrelated sales, and neither finance nor a retry can tell which
receipt is the live one.

The one-receipt-per-payment guard from f1c8d3b5a207 forbids that second row, so
it narrows here to one *live* receipt per payment. The guard's point stands —
a payment must never hold two valid DDTDs — and a returned receipt is not one.

Revision ID: c1d4f2a70b83
Revises: b5e93a1c4d76
Create Date: 2026-08-16

"""
import sqlalchemy as sa
from alembic import op

revision = "c1d4f2a70b83"
down_revision = "b5e93a1c4d76"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ebarimt_receipts", sa.Column("replaces_receipt_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_ebarimt_receipts_replaces_receipt_id",
        "ebarimt_receipts",
        ["replaces_receipt_id"],
    )
    op.create_foreign_key(
        "fk_ebarimt_receipts_replaces_receipt_id",
        "ebarimt_receipts",
        "ebarimt_receipts",
        ["replaces_receipt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("uq_ebarimt_receipts_payment", table_name="ebarimt_receipts")
    op.create_index(
        "uq_ebarimt_receipts_payment",
        "ebarimt_receipts",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL AND status <> 'returned'"),
    )


def downgrade():
    op.drop_index("uq_ebarimt_receipts_payment", table_name="ebarimt_receipts")
    op.create_index(
        "uq_ebarimt_receipts_payment",
        "ebarimt_receipts",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("payment_id IS NOT NULL"),
    )
    op.drop_constraint(
        "fk_ebarimt_receipts_replaces_receipt_id", "ebarimt_receipts", type_="foreignkey"
    )
    op.drop_index("ix_ebarimt_receipts_replaces_receipt_id", table_name="ebarimt_receipts")
    op.drop_column("ebarimt_receipts", "replaces_receipt_id")
