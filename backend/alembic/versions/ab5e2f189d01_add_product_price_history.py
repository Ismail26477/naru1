"""Add product_price_history table + products.description column."""

from alembic import op
import sqlalchemy as sa


revision = "ab5e2f189d01"
down_revision = "c7e91b3a4d22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("description", sa.Text(), nullable=True))
    op.create_table(
        "product_price_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("price_paise", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_price_history_product_id", "product_price_history", ["product_id"])
    op.create_index("ix_product_price_history_effective_from", "product_price_history", ["effective_from"])
    op.create_index("ix_product_price_history_lookup", "product_price_history", ["product_id", "effective_from"])

    # Backfill: one history row per product with effective_from = today_UTC (approximate).
    # Forward-safe — lookups past this date use the single existing price.
    op.execute(
        """
        INSERT INTO product_price_history (id, product_id, price_paise, effective_from, changed_by, reason, created_at)
        SELECT gen_random_uuid(), id, price_paise, CURRENT_DATE - INTERVAL '365 days',
               NULL, 'Backfilled from products.price_paise (Phase 2B.5 migration)', NOW()
        FROM products
        """
    )


def downgrade() -> None:
    op.drop_index("ix_product_price_history_lookup", table_name="product_price_history")
    op.drop_index("ix_product_price_history_effective_from", table_name="product_price_history")
    op.drop_index("ix_product_price_history_product_id", table_name="product_price_history")
    op.drop_table("product_price_history")
    op.drop_column("products", "description")
