"""Create aviation parts, supplier quotes, and purchase orders.

Revision ID: 0001_aviation_parts_and_po
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_aviation_parts_and_po"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aviation_parts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("part_number", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("condition_code", sa.String(8)),
        sa.Column("unit_price", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("warranty_terms", sa.Text()),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_aviation_parts_part_number", "aviation_parts", ["part_number"], unique=True)
    op.create_table(
        "supplier_quotes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("supplier_email", sa.String(320), nullable=False),
        sa.Column("part_id", sa.String(64), sa.ForeignKey("aviation_parts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quoted_price", sa.Numeric(12, 2)),
        sa.Column("raw_email_id", sa.String(128), unique=True),
        sa.Column("has_trace_docs", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attachment_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_supplier_quotes_supplier_email", "supplier_quotes", ["supplier_email"])
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("po_number", sa.String(64), nullable=False, unique=True),
        sa.Column("customer_email", sa.String(320), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="Pending_PO_Review"),
        sa.Column("po_document_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("purchase_orders")
    op.drop_index("ix_supplier_quotes_supplier_email", table_name="supplier_quotes")
    op.drop_table("supplier_quotes")
    op.drop_index("ix_aviation_parts_part_number", table_name="aviation_parts")
    op.drop_table("aviation_parts")
