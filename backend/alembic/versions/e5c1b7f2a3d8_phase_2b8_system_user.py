"""Phase 2B.8: is_system flag on users + seed the singleton automation user.

- Adds users.is_system BOOL NOT NULL DEFAULT FALSE
- Partial unique index so there is at most ONE is_system=true user
- Seeds the system user: phone='+910000000000', name='System (Automated)', role=admin
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e5c1b7f2a3d8"
down_revision = "d8f2a4b1c7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "is_system", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    # Singleton: only one is_system=true user may exist.
    op.create_index(
        "uq_users_is_system_true",
        "users", ["is_system"],
        unique=True,
        postgresql_where=sa.text("is_system = true"),
    )
    # Seed the system user (idempotent via phone uniqueness).
    op.execute("""
        INSERT INTO users (id, phone, name, role, is_active, approved_at, is_system, wallet_balance_paise, created_at)
        VALUES (
            gen_random_uuid(),
            '+910000000000',
            'System (Automated)',
            'ADMIN',
            true,
            NOW(),
            true,
            0,
            NOW()
        )
        ON CONFLICT (phone) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE phone = '+910000000000' AND is_system = true")
    op.drop_index("uq_users_is_system_true", table_name="users")
    op.drop_column("users", "is_system")
