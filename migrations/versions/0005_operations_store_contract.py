"""Add columns and tables required by the synchronous operational store."""

from alembic import op
import sqlalchemy as sa


revision = "0005_operations_store_contract"
down_revision = "0004_review_telemetry_postgres"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_records",
        sa.Column("domain", sa.String(64), primary_key=True),
        sa.Column("record_id", sa.String(128), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_operational_records_domain_updated", "operational_records", ["domain", "updated_at"])

    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(64)),
        sa.Column("approval_status", sa.String(32), nullable=False, server_default="Pending"),
        sa.Column("itar_certified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(32), nullable=False, server_default="email"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_suppliers_company_name", "suppliers", ["company_name"])
    op.create_index("ix_suppliers_email", "suppliers", ["email"])

    op.create_table(
        "supplier_parts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("part_number", sa.String(80), nullable=False),
        sa.Column("condition_code", sa.String(8)),
        sa.Column("description", sa.Text()),
        sa.Column("quantity_available", sa.Integer()),
        sa.Column("unit_cost", sa.Float()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("certificate_type", sa.String(128)),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("availability_location", sa.String(255)),
        sa.Column("warranty_terms", sa.Text()),
        sa.Column("trace_documents", sa.Text()),
        sa.Column("source_email_id", sa.String(512), unique=True),
        sa.Column("confidence", sa.Float()),
        sa.Column("approval_status", sa.String(32), nullable=False, server_default="Pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_supplier_parts_supplier_id", "supplier_parts", ["supplier_id"])
    op.create_index("ix_supplier_parts_part_number", "supplier_parts", ["part_number"])

    op.create_table(
        "inbound_emails",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mailbox", sa.String(128), nullable=False),
        sa.Column("message_id", sa.String(512), nullable=False, unique=True),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("extraction_error", sa.Text()),
    )
    op.create_index("ix_inbound_emails_mailbox", "inbound_emails", ["mailbox"])
    op.create_index("ix_inbound_emails_message_id", "inbound_emails", ["message_id"])

    for name, column, default in (
        ("task_type", sa.String(64), "email"),
        ("mailbox", sa.String(128), "sales"),
        ("reply_to", sa.String(512), None),
        ("attempts", sa.Integer(), "0"),
        ("max_attempts", sa.Integer(), "5"),
        ("last_error", sa.Text(), None),
        ("sent_at", sa.DateTime(timezone=True), None),
    ):
        op.add_column("communication_tasks", sa.Column(name, column, nullable=True, server_default=default))
    op.execute("UPDATE communication_tasks SET task_type = 'email' WHERE task_type IS NULL")
    op.execute("UPDATE communication_tasks SET mailbox = 'sales' WHERE mailbox IS NULL")
    op.execute("UPDATE communication_tasks SET attempts = 0 WHERE attempts IS NULL")
    op.execute("UPDATE communication_tasks SET max_attempts = 5 WHERE max_attempts IS NULL")
    for name in ("task_type", "mailbox", "attempts", "max_attempts"):
        op.alter_column("communication_tasks", name, nullable=False)

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("deduplication_key", sa.String(255), nullable=False, unique=True),
        sa.Column("entity_id", sa.String(128)),
        sa.Column("mailbox", sa.String(128), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reply_to", sa.String(512)),
        sa.Column("communication_task_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("error_message", sa.Text()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sending_started_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_messages_status", "outbox_messages", ["status", "available_at"])
    op.create_index("ix_outbox_messages_task", "outbox_messages", ["communication_task_id"])
    op.create_index("ix_outbox_messages_entity", "outbox_messages", ["entity_id"])

    op.create_table(
        "customers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255)),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customers_email", "customers", ["email"])

    for name, column in (
        ("customer_id", sa.String(64)),
        ("part_number", sa.String(80)),
        ("description", sa.Text()),
        ("quantity", sa.Integer()),
        ("condition_requested", sa.String(32)),
        ("certification_requested", sa.String(255)),
        ("destination", sa.String(512)),
    ):
        op.add_column("rfqs", sa.Column(name, column, nullable=True))
    op.create_index("ix_rfqs_customer_id", "rfqs", ["customer_id"])

    for name, column in (
        ("entity_type", sa.String(64)),
        ("channel", sa.String(32)),
        ("message_type", sa.String(32)),
        ("sent_at", sa.DateTime(timezone=True)),
        ("response_received", sa.Text()),
    ):
        op.add_column("communications", sa.Column(name, column, nullable=True))

    op.create_table(
        "customer_quotes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("rfq_id", sa.String(64), nullable=False),
        sa.Column("quote_number", sa.String(64), nullable=False, unique=True),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("total_price", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("lead_time", sa.Integer()),
        sa.Column("condition", sa.String(32)),
        sa.Column("certification", sa.String(255)),
        sa.Column("valid_until", sa.String(64)),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_quotes_rfq_id", "customer_quotes", ["rfq_id"])

    op.create_table(
        "customer_quote_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("quote_id", sa.String(64), nullable=False),
        sa.Column("rfq_item_id", sa.String(64)),
        sa.Column("part_number", sa.String(80), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(32)),
        sa.Column("certification", sa.String(255), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("lead_time", sa.Integer()),
        sa.Column("attachments", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_quote_items_quote_id", "customer_quote_items", ["quote_id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_status", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_task", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_entity", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index("ix_inbound_emails_message_id", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_mailbox", table_name="inbound_emails")
    op.drop_table("inbound_emails")
    for name in ("sent_at", "last_error", "max_attempts", "attempts", "reply_to", "mailbox", "task_type"):
        op.drop_column("communication_tasks", name)
    op.drop_index("ix_supplier_parts_part_number", table_name="supplier_parts")
    op.drop_index("ix_supplier_parts_supplier_id", table_name="supplier_parts")
    op.drop_table("supplier_parts")
    op.drop_index("ix_suppliers_email", table_name="suppliers")
    op.drop_index("ix_suppliers_company_name", table_name="suppliers")
    op.drop_table("suppliers")
    op.drop_index("ix_operational_records_domain_updated", table_name="operational_records")
    op.drop_table("operational_records")
    op.drop_index("ix_customer_quote_items_quote_id", table_name="customer_quote_items")
    op.drop_table("customer_quote_items")
    op.drop_index("ix_customer_quotes_rfq_id", table_name="customer_quotes")
    op.drop_table("customer_quotes")
    op.drop_column("communications", "response_received")
    op.drop_column("communications", "sent_at")
    op.drop_column("communications", "message_type")
    op.drop_column("communications", "channel")
    op.drop_column("communications", "entity_type")
    op.drop_index("ix_rfqs_customer_id", table_name="rfqs")
    op.drop_column("rfqs", "destination")
    op.drop_column("rfqs", "certification_requested")
    op.drop_column("rfqs", "condition_requested")
    op.drop_column("rfqs", "quantity")
    op.drop_column("rfqs", "description")
    op.drop_column("rfqs", "part_number")
    op.drop_column("rfqs", "customer_id")
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_table("customers")