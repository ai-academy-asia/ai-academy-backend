"""Record why a payment was refunded

The pilot refund rule is captured as a number (refund_pct_attended), but finance
also has to answer *why* months later, and a percentage does not say whether the
buyer withdrew, was moved to another cohort, or paid twice. One nullable column,
written by the refund endpoint.

Revision ID: b5e93a1c4d76
Revises: a2f7c4d81b09
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op

revision = "b5e93a1c4d76"
down_revision = "a2f7c4d81b09"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("refund_reason", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("payments", "refund_reason")
