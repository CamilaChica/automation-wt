"""Archive raw inbound email, track bulk inventory imports, and keep RFQ line pricing."""

from alembic import op


revision = "0008_raw_email_inventory_imports"
down_revision = "0007_employee_time_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS quote_id VARCHAR(64)")
    op.execute("ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS rfq_id VARCHAR(64)")
    op.execute("ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS received_message_id VARCHAR(512)")
    op.execute("ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS attachment_metadata JSONB")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_orders_received_message ON purchase_orders (received_message_id) WHERE received_message_id IS NOT NULL")
    op.execute("ALTER TABLE rfq_items ADD COLUMN description TEXT")
    op.execute("ALTER TABLE rfq_items ADD COLUMN target_price DOUBLE PRECISION")
    op.execute("ALTER TABLE rfq_items ADD COLUMN currency VARCHAR(3)")
    op.execute("""
        CREATE TABLE audit_logs (
            id BIGSERIAL PRIMARY KEY,
            rfq_id VARCHAR(64) NOT NULL,
            agent_name VARCHAR(128) NOT NULL,
            action_type VARCHAR(128) NOT NULL,
            message TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
            payload_json TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_audit_logs_rfq_created ON audit_logs (rfq_id, created_at)")
    op.execute("""
        INSERT INTO audit_logs (rfq_id, agent_name, action_type, message, status, payload_json, created_at)
        SELECT payload->>'rfq_id', payload->>'agent_name', payload->>'action_type', payload->>'message',
               COALESCE(payload->>'status', 'SUCCESS'), payload->>'payload_json',
               COALESCE(NULLIF(payload->>'timestamp', '')::timestamptz, updated_at)
        FROM operational_records
        WHERE domain = 'audit_logs'
          AND COALESCE(payload->>'rfq_id', '') <> ''
          AND COALESCE(payload->>'message', '') <> ''
    """)
    op.execute("""
        CREATE TABLE raw_emails (
            id VARCHAR(64) PRIMARY KEY,
            mailbox VARCHAR(128) NOT NULL,
            provider_message_id VARCHAR(512) NOT NULL,
            internet_message_id VARCHAR(998),
            conversation_id VARCHAR(512),
            sender VARCHAR(320),
            subject TEXT,
            received_at TIMESTAMPTZ,
            body TEXT NOT NULL DEFAULT '',
            raw_mime BYTEA,
            headers JSONB,
            attachments JSONB,
            processing_status VARCHAR(32) NOT NULL DEFAULT 'received',
            archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_raw_emails_mailbox_provider_message UNIQUE (mailbox, provider_message_id)
        )
    """)
    op.execute("CREATE INDEX ix_raw_emails_internet_message_id ON raw_emails (internet_message_id)")
    op.execute("CREATE INDEX ix_raw_emails_mailbox_received ON raw_emails (mailbox, received_at)")
    op.execute("""
        CREATE TABLE supplier_inventory_imports (
            id VARCHAR(64) PRIMARY KEY,
            mailbox VARCHAR(128) NOT NULL,
            source_message_id VARCHAR(512) NOT NULL,
            sender VARCHAR(320),
            filename TEXT NOT NULL,
            content_sha256 CHAR(64) NOT NULL,
            parser VARCHAR(32) NOT NULL,
            sheet_name TEXT,
            header_map JSONB,
            rows_total INTEGER NOT NULL DEFAULT 0,
            rows_imported INTEGER NOT NULL DEFAULT 0,
            rows_rejected INTEGER NOT NULL DEFAULT 0,
            rejected_rows JSONB,
            status VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_supplier_inventory_imports_source UNIQUE (source_message_id, content_sha256)
        )
    """)
    op.execute("CREATE INDEX ix_supplier_inventory_imports_created ON supplier_inventory_imports (created_at)")
    op.execute("""
        CREATE TABLE supplier_inventory_rows (
            id VARCHAR(64) PRIMARY KEY,
            import_id VARCHAR(64) NOT NULL REFERENCES supplier_inventory_imports(id) ON DELETE CASCADE,
            row_number INTEGER NOT NULL,
            part_number VARCHAR(128),
            description TEXT,
            quantity_available INTEGER,
            condition_code VARCHAR(32),
            unit_price DOUBLE PRECISION,
            currency VARCHAR(3),
            lead_time_days INTEGER,
            certificate_type TEXT,
            availability_location TEXT,
            raw_values JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(32) NOT NULL,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_supplier_inventory_rows_import_row UNIQUE (import_id, row_number)
        )
    """)
    op.execute("CREATE INDEX ix_supplier_inventory_rows_part_number ON supplier_inventory_rows (part_number)")
    op.execute("""
        CREATE TABLE negotiation_sessions (
            id VARCHAR(64) PRIMARY KEY,
            supplier_email VARCHAR(320) NOT NULL,
            part_number VARCHAR(128) NOT NULL,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_negotiation_sessions_supplier_part UNIQUE (supplier_email, part_number)
        )
    """)
    op.execute("CREATE INDEX ix_audit_events_entity_created ON audit_events (entity_id, created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_purchase_orders_received_message")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS attachment_metadata")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS received_message_id")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS rfq_id")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS quote_id")
    op.drop_index("ix_audit_events_entity_created", table_name="audit_events")
    op.drop_index("ix_supplier_inventory_rows_part_number", table_name="supplier_inventory_rows")
    op.drop_table("supplier_inventory_rows")
    op.drop_table("negotiation_sessions")
    op.drop_index("ix_supplier_inventory_imports_created", table_name="supplier_inventory_imports")
    op.drop_table("supplier_inventory_imports")
    op.drop_index("ix_raw_emails_mailbox_received", table_name="raw_emails")
    op.drop_index("ix_raw_emails_internet_message_id", table_name="raw_emails")
    op.drop_table("raw_emails")
    op.drop_index("ix_audit_logs_rfq_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.execute("ALTER TABLE rfq_items DROP COLUMN currency")
    op.execute("ALTER TABLE rfq_items DROP COLUMN target_price")
    op.execute("ALTER TABLE rfq_items DROP COLUMN description")
