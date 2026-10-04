"""Add database-backed aviation business policies for advisory DSPy context."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0013_database_business_policies"
down_revision = "0012_supplier_offer_received_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_policies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("policy_key", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("policy_data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_business_policies_policy_key", "business_policies", ["policy_key"], unique=True)
    op.create_index("ix_business_policies_category", "business_policies", ["category"])
    op.create_index("ix_business_policies_is_active", "business_policies", ["is_active"])
    op.execute("""
        INSERT INTO business_policies
            (id, policy_key, title, category, description, policy_data)
        VALUES
            (
                'business-policy-auto-quote-v1',
                'automatic_quote_dispatch',
                'Automatic quote dispatch limits',
                'quote_automation',
                'Existing backend auto-dispatch thresholds. DSPy may recommend an outcome but cannot authorize dispatch.',
                '{"min_extraction_confidence": 0.92, "min_gross_margin": 0.18, "max_auto_approve_value": 25000.0, "strict_zero_sanctions": true, "approved_compliance_statuses": ["APPROVED", "PASS", "PASSED", "CLEAR"]}'::jsonb
            ),
            (
                'business-policy-supplier-currency-v1',
                'supplier_currency',
                'Supplier quote currency handling',
                'supplier_sourcing',
                'Supplier offers with a non-USD currency require human review under the existing backend workflow.',
                '{"accepted_currency": "USD", "non_usd_action": "review"}'::jsonb
            ),
            (
                'business-policy-supplier-evidence-v1',
                'supplier_quote_evidence',
                'Supplier offer evidence requirements',
                'supplier_sourcing',
                'Supplier quote facts must be explicitly supported by the source email or attachment and incomplete records require review.',
                '{"source_grounding_required": true, "missing_or_conflicting_fields_action": "review"}'::jsonb
            ),
            (
                'business-policy-customer-privacy-v1',
                'customer_communication_privacy',
                'Customer communication disclosure limits',
                'customer_communication',
                'Customer messages must not disclose supplier costs, internal margins, supplier identities, warehouse locations, credentials, or private audit details.',
                '{"never_disclose": ["supplier costs", "internal margins", "supplier identities", "warehouse locations", "credentials", "private audit details"]}'::jsonb
            ),
            (
                'business-policy-supplier-communication-v1',
                'supplier_communication_scope',
                'Supplier communication scope',
                'supplier_communication',
                'Supplier emails may request verified sourcing information but must not commit to an order or imply that an offer was accepted.',
                '{"request_only_verified_fields": true, "no_order_commitment": true}'::jsonb
            )
    """)


def downgrade() -> None:
    op.drop_index("ix_business_policies_is_active", table_name="business_policies")
    op.drop_index("ix_business_policies_category", table_name="business_policies")
    op.drop_index("ix_business_policies_policy_key", table_name="business_policies")
    op.drop_table("business_policies")
