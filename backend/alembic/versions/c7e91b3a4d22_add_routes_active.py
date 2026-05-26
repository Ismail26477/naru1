"""Phase 2B.3: add routes.active column."""

from alembic import op
import sqlalchemy as sa


revision = "c7e91b3a4d22"
down_revision = "8d4c1a2e5f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.create_index("ix_routes_active", "routes", ["active"])


def downgrade() -> None:
    op.drop_index("ix_routes_active", table_name="routes")
    op.drop_column("routes", "active")
