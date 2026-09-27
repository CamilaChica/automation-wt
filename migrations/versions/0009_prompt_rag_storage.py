"""Persist prompt configuration and RAG vectors."""

from alembic import op


revision = "0009_prompt_rag_storage"
down_revision = "0008_raw_email_inventory_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE prompt_techniques (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL UNIQUE,
            description TEXT NOT NULL,
            template TEXT NOT NULL,
            examples JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE prompt_security_policies (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL UNIQUE,
            sanitize_input BOOLEAN NOT NULL DEFAULT TRUE,
            detect_injection BOOLEAN NOT NULL DEFAULT TRUE,
            mask_pii BOOLEAN NOT NULL DEFAULT TRUE,
            prevent_jailbreaks BOOLEAN NOT NULL DEFAULT TRUE,
            block_injection BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE scaling_prompts (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            template TEXT NOT NULL,
            variables JSONB NOT NULL DEFAULT '[]'::jsonb,
            prompt_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_scaling_prompts_name_version UNIQUE (name, version)
        )
    """)
    op.execute("CREATE INDEX ix_scaling_prompts_name ON scaling_prompts (name)")
    op.execute("""
        CREATE TABLE rag_vector_records (
            id VARCHAR(64) PRIMARY KEY,
            namespace VARCHAR(256) NOT NULL,
            text TEXT NOT NULL,
            embedding JSONB NOT NULL,
            embedding_provider VARCHAR(32) NOT NULL,
            embedding_model VARCHAR(128) NOT NULL,
            record_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_rag_vector_records_namespace ON rag_vector_records (namespace)")


def downgrade() -> None:
    op.drop_index("ix_rag_vector_records_namespace", table_name="rag_vector_records")
    op.drop_table("rag_vector_records")
    op.drop_index("ix_scaling_prompts_name", table_name="scaling_prompts")
    op.drop_table("scaling_prompts")
    op.drop_table("prompt_security_policies")
    op.drop_table("prompt_techniques")