"""Phase 2B.6: billing reconciliation — adjustments table, payment ref, invoice metadata.

Adds the state needed for billing ops:
- invoices.has_post_billing_adjustments     ← flipped when a delivered order is
                                               overridden after the invoice was issued
- invoices.regenerated_count                ← bumped each regenerate
- invoices.last_regenerated_at/by           ← audit trail pointers
- invoices.amount_paid_paise                ← cached SUM(payments.successful) for fast status calc
- invoice_status += 'partially_paid'
- payment_method += 'upi', 'bank_transfer'
- payments.reference                        ← free-text ref (UTR / txn id / etc.)
- invoice_adjustments                        ← signed ledger of wallet_credit /
                                               manual_credit / manual_debit / override_adjustment
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d8f2a4b1c7e9"
down_revision = "ab5e2f189d01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum value additions — postgres requires ALTER TYPE ... ADD VALUE outside txn.
    # Alembic 1.13 handles this via execute with autocommit-like semantics.
    op.execute("ALTER TYPE invoice_status ADD VALUE IF NOT EXISTS 'partially_paid'")
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'upi'")
    op.execute("ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'bank_transfer'")

    # invoices columns
    op.add_column("invoices", sa.Column("regenerated_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("invoices", sa.Column("has_post_billing_adjustments", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("invoices", sa.Column("amount_paid_paise", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("invoices", sa.Column("last_regenerated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("last_regenerated_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_invoices_last_regenerated_by_users",
        "invoices", "users",
        ["last_regenerated_by"], ["id"], ondelete="SET NULL",
    )

    # payments.reference
    op.add_column("payments", sa.Column("reference", sa.String(length=255), nullable=True))

    # invoice_adjustments table
    op.create_table(
        "invoice_adjustments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        # Signed paise: negative reduces amount due (credit to customer),
        # positive increases amount due (debit / manual surcharge).
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reference_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_invoice_adjustments_invoice_id", "invoice_adjustments", ["invoice_id"])
    op.create_index("ix_invoice_adjustments_kind", "invoice_adjustments", ["kind"])
    op.create_index("ix_invoice_adjustments_created_at", "invoice_adjustments", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_invoice_adjustments_created_at", table_name="invoice_adjustments")
    op.drop_index("ix_invoice_adjustments_kind", table_name="invoice_adjustments")
    op.drop_index("ix_invoice_adjustments_invoice_id", table_name="invoice_adjustments")
    op.drop_table("invoice_adjustments")

    op.drop_column("payments", "reference")

    op.drop_constraint("fk_invoices_last_regenerated_by_users", "invoices", type_="foreignkey")
    op.drop_column("invoices", "last_regenerated_by")
    op.drop_column("invoices", "last_regenerated_at")
    op.drop_column("invoices", "amount_paid_paise")
    op.drop_column("invoices", "has_post_billing_adjustments")
    op.drop_column("invoices", "regenerated_count")
    # Postgres doesn't support DROP VALUE on enums cleanly; leave the enum values in place on downgrade.
