"""Map every legacy schedule id the marketing site can send onto a cohort

The old system expressed payment terms as separate schedule rows: one id for the
full price, another for the same class at a deposit, more for the promo variants.
The site still holds those ids and posts whichever the buyer picked, so the
backend has to resolve all of them — 39 ids across 23 runs, of which only the 23
full-price ones were stored.

charge_percent travels with the id because the id is the only signal we get:
without it a buyer choosing a 50% deposit is invoiced for 100%.

Revision ID: a2f7c4d81b09
Revises: f1c8d3b5a207
Create Date: 2026-08-06

"""
import sqlalchemy as sa
from alembic import op

revision = "a2f7c4d81b09"
down_revision = "f1c8d3b5a207"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cohort_legacy_schedules",
        sa.Column("legacy_schedule_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="full"),
        sa.Column(
            "charge_percent", sa.Numeric(5, 2), nullable=False, server_default="100"
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("legacy_schedule_id"),
    )
    op.create_index(
        "ix_cohort_legacy_schedules_cohort_id",
        "cohort_legacy_schedules",
        ["cohort_id"],
    )


def downgrade():
    op.drop_index(
        "ix_cohort_legacy_schedules_cohort_id", table_name="cohort_legacy_schedules"
    )
    op.drop_table("cohort_legacy_schedules")
