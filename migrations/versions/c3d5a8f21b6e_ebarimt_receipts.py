"""ebarimt receipts (temp-mode e-receipt)

Revision ID: c3d5a8f21b6e
Revises: b7e2f1a9c4d3
Create Date: 2026-07-24 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d5a8f21b6e'
down_revision = 'b7e2f1a9c4d3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ebarimt_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('invoice_id', sa.Integer(), nullable=True),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('customer_register', sa.String(length=20), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('vat_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('city_tax_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('district_code', sa.String(length=10), nullable=True),
        sa.Column('pos_no', sa.String(length=40), nullable=True),
        sa.Column('is_temp_mode', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('ebarimt_id', sa.String(length=64), nullable=True),
        sa.Column('lottery', sa.String(length=20), nullable=True),
        sa.Column('qr_data', sa.Text(), nullable=True),
        sa.Column('raw', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('returned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ebarimt_receipts', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_ebarimt_receipts_payment_id'), ['payment_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_ebarimt_receipts_invoice_id'), ['invoice_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_ebarimt_receipts_is_temp_mode'), ['is_temp_mode'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_ebarimt_receipts_status'), ['status'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_ebarimt_receipts_ebarimt_id'), ['ebarimt_id'], unique=False)


def downgrade():
    with op.batch_alter_table('ebarimt_receipts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ebarimt_receipts_ebarimt_id'))
        batch_op.drop_index(batch_op.f('ix_ebarimt_receipts_status'))
        batch_op.drop_index(batch_op.f('ix_ebarimt_receipts_is_temp_mode'))
        batch_op.drop_index(batch_op.f('ix_ebarimt_receipts_invoice_id'))
        batch_op.drop_index(batch_op.f('ix_ebarimt_receipts_payment_id'))
    op.drop_table('ebarimt_receipts')
