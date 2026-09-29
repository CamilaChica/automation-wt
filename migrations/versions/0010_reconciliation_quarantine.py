"""Add inactive quarantine tables for legacy reconciliation."""

from alembic import op
import sqlalchemy as sa


revision = "0010_reconciliation_quarantine"
down_revision = "0009_prompt_rag_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quarantine_quote_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("quote_id", sa.String(64)),
        sa.Column("rfq_id", sa.String(64)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quarantine_quote_items_source_id", "quarantine_quote_items", ["source_id"])

    op.create_table(
        "quarantine_supplier_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("matched_supplier_id", sa.String(64)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_quarantine_supplier_profiles_source_id", "quarantine_supplier_profiles", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_quarantine_supplier_profiles_source_id", table_name="quarantine_supplier_profiles")
    op.drop_table("quarantine_supplier_profiles")
    op.drop_index("ix_quarantine_quote_items_source_id", table_name="quarantine_quote_items")
    op.drop_table("quarantine_quote_items")