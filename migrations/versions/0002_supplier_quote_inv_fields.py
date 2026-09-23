"""Add searchable supplier quote inventory fields."""

from alembic import op
import sqlalchemy as sa

revision = "0002_supplier_quote_inv_fields"
down_revision = "0001_aviation_parts_and_po"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column in (
        ("quantity_available", sa.Column("quantity_available", sa.Integer())),
        ("condition_code", sa.Column("condition_code", sa.String(8))),
        ("certificate_type", sa.Column("certificate_type", sa.String(64))),
        ("lead_time_days", sa.Column("lead_time_days", sa.Integer())),
        ("availability_location", sa.Column("availability_location", sa.Text())),
        ("warranty_terms", sa.Column("warranty_terms", sa.Text())),
        ("trace_documents", sa.Column("trace_documents", sa.Text())),
    ):
        op.add_column("supplier_quotes", column)
    op.create_index("ix_supplier_quotes_part_id_created_at", "supplier_quotes", ["part_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_supplier_quotes_part_id_created_at", table_name="supplier_quotes")
    for name in ("trace_documents", "warranty_terms", "availability_location", "lead_time_days", "certificate_type", "condition_code", "quantity_available"):
        op.drop_column("supplier_quotes", name)