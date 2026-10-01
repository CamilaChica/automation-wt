"""Merge shared-auth and reconciliation migration heads."""


revision = "0011_merge_postgres_migration_heads"
down_revision = ("0010_reconciliation_quarantine", "0010_shared_auth_state")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
