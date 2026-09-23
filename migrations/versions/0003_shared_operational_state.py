"""Create shared operational PostgreSQL state tables."""

from alembic import op
import sqlalchemy as sa

revision = "0003_shared_operational_state"
down_revision = "0002_supplier_quote_inv_fields"
branch_labels = None
depends_on = None


def _table(name: str, columns: list[sa.Column], indexes: list[tuple[str, list[str]]] = ()) -> None:
    op.create_table(name, *columns)
    for index_name, fields in indexes:
        op.create_index(index_name, name, fields)


def upgrade() -> None:
    _table("rfqs", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("customer_email", sa.String(320), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="Intake"),
        sa.Column("thread_id", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_rfqs_customer_email", ["customer_email"]), ("ix_rfqs_status", ["status"])])
    _table("rfq_items", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("rfq_id", sa.String(64), nullable=False),
        sa.Column("part_number", sa.String(80), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition_code", sa.String(8)),
        sa.Column("details", sa.JSON()),
    ], [("ix_rfq_items_rfq_id", ["rfq_id"]), ("ix_rfq_items_part_number", ["part_number"])])
    _table("supplier_offers", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("rfq_id", sa.String(64)),
        sa.Column("supplier_email", sa.String(320), nullable=False),
        sa.Column("part_number", sa.String(80), nullable=False),
        sa.Column("quantity_available", sa.Integer()),
        sa.Column("unit_cost", sa.Float()),
        sa.Column("condition_code", sa.String(8)),
        sa.Column("certificate_type", sa.String(64)),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("source_message_id", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_supplier_offers_rfq_id", ["rfq_id"]), ("ix_supplier_offers_supplier_email", ["supplier_email"]), ("ix_supplier_offers_part_number", ["part_number"]), ("ix_supplier_offers_source_message_id", ["source_message_id"])])
    _table("quotes", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("rfq_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="Draft"),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_quotes_rfq_id", ["rfq_id"]), ("ix_quotes_status", ["status"])])
    _table("quote_items", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("quote_id", sa.String(64), nullable=False),
        sa.Column("part_number", sa.String(80), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("details", sa.JSON()),
    ], [("ix_quote_items_quote_id", ["quote_id"])])
    _table("communications", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_communications_entity_id", ["entity_id"]), ("ix_communications_status", ["status"])])
    _table("audit_events", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_audit_events_entity_id", ["entity_id"])])
    _table("workflow_state", [
        sa.Column("entity_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_workflow_state_state", ["state"])])
    _table("communication_tasks", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_key", sa.String(255), nullable=False, unique=True),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_communication_tasks_status", ["status"])])
    _table("inbound_message_idempotency", [
        sa.Column("message_id", sa.String(512), primary_key=True),
        sa.Column("mailbox", sa.String(128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(32), nullable=False, server_default="processed"),
    ], [("ix_inbound_message_idempotency_mailbox", ["mailbox"])])
    _table("agent_handoffs", [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("from_agent", sa.String(128), nullable=False),
        sa.Column("to_agent", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ], [("ix_agent_handoffs_entity_id", ["entity_id"])])


def downgrade() -> None:
    for table in ("agent_handoffs", "inbound_message_idempotency", "communication_tasks", "workflow_state", "audit_events", "communications", "quote_items", "quotes", "supplier_offers", "rfq_items", "rfqs"):
        op.drop_table(table)
