"""Phase 2C: invoice PDF cache columns.

- Adds invoices.pdf_generated_at  DateTime(tz=True) NULL
- Adds invoices.pdf_storage_path  VARCHAR(500) NULL

Lazy-generation + invalidation is handled in the service layer; these columns
simply mark whether a cached PDF is available for a given invoice.
"""
from alembic import op
import sqlalchemy as sa


revision = "f1a3c5e8b2d4"
down_revision = "e5c1b7f2a3d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column(
        "pdf_generated_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("invoices", sa.Column(
        "pdf_storage_path", sa.String(500), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("invoices", "pdf_storage_path")
    op.drop_column("invoices", "pdf_generated_at")
