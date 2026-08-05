"""payments: invoices, payments, installments, student_ledger

Revision ID: b7e2f1a9c4d3
Revises: 4da730ec1a17
Create Date: 2026-07-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e2f1a9c4d3'
down_revision = '4da730ec1a17'
branch_labels = None
depends_on = None


def upgrade():
    # --- payment_installments (referenced by invoices.installment_id) ---
    op.create_table(
        'payment_installments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('enrollment_id', 'seq', name='uq_installment_enrollment_seq'),
    )
    with op.batch_alter_table('payment_installments', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_payment_installments_enrollment_id'), ['enrollment_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_payment_installments_student_id'), ['student_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_payment_installments_status'), ['status'], unique=False)

    # --- invoices ---
    op.create_table(
        'invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), nullable=True),
        sa.Column('student_id', sa.Integer(), nullable=True),
        sa.Column('installment_id', sa.Integer(), nullable=True),
        sa.Column('sender_invoice_no', sa.String(length=64), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('provider_invoice_id', sa.String(length=120), nullable=True),
        sa.Column('qr_text', sa.Text(), nullable=True),
        sa.Column('qr_image', sa.Text(), nullable=True),
        sa.Column('payment_url', sa.String(length=500), nullable=True),
        sa.Column('urls', sa.JSON(), nullable=True),
        sa.Column('provider_meta', sa.JSON(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['installment_id'], ['payment_installments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sender_invoice_no', name='uq_invoice_sender_invoice_no'),
    )
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_invoices_provider'), ['provider'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_invoices_enrollment_id'), ['enrollment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoices_student_id'), ['student_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_invoices_installment_id'), ['installment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoices_status'), ['status'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_invoices_provider_invoice_id'), ['provider_invoice_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_invoices_sender_invoice_no'), ['sender_invoice_no'], unique=True)

    # --- payments ---
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_payment_id', sa.String(length=120), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('refunded_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('refund_pct_attended', sa.Integer(), nullable=True),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
        sa.Column('raw', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_payment_id', name='uq_payment_provider_txn'),
    )
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payments_invoice_id'), ['invoice_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_provider'), ['provider'], unique=False)

    # --- student_ledger ---
    op.create_table(
        'student_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('enrollment_id', sa.Integer(), nullable=False),
        sa.Column('total_due', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_paid', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('next_due_date', sa.Date(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('enrollment_id', name='uq_ledger_enrollment'),
    )
    with op.batch_alter_table('student_ledger', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_student_ledger_student_id'), ['student_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_student_ledger_enrollment_id'), ['enrollment_id'], unique=True)


def downgrade():
    with op.batch_alter_table('student_ledger', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_student_ledger_enrollment_id'))
        batch_op.drop_index(batch_op.f('ix_student_ledger_student_id'))
    op.drop_table('student_ledger')

    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_provider'))
        batch_op.drop_index(batch_op.f('ix_payments_invoice_id'))
    op.drop_table('payments')

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invoices_sender_invoice_no'))
        batch_op.drop_index(batch_op.f('ix_invoices_provider_invoice_id'))
        batch_op.drop_index(batch_op.f('ix_invoices_status'))
        batch_op.drop_index(batch_op.f('ix_invoices_installment_id'))
        batch_op.drop_index(batch_op.f('ix_invoices_student_id'))
        batch_op.drop_index(batch_op.f('ix_invoices_enrollment_id'))
        batch_op.drop_index(batch_op.f('ix_invoices_provider'))
    op.drop_table('invoices')

    with op.batch_alter_table('payment_installments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_installments_status'))
        batch_op.drop_index(batch_op.f('ix_payment_installments_student_id'))
        batch_op.drop_index(batch_op.f('ix_payment_installments_enrollment_id'))
    op.drop_table('payment_installments')
