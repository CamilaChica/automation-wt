"""Store production authentication state in shared PostgreSQL."""

from alembic import op


revision = "0010_shared_auth_state"
down_revision = "0009_prompt_rag_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE auth_users (
            id VARCHAR(128) PRIMARY KEY,
            email VARCHAR(320) NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            role VARCHAR(64) NOT NULL,
            is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL,
            last_activity_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE auth_otp_challenges (
            id VARCHAR(128) PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            role VARCHAR(64) NOT NULL,
            code_hash CHAR(64) NOT NULL,
            expires_at BIGINT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            request_window_started BIGINT NOT NULL,
            request_count INTEGER NOT NULL DEFAULT 1,
            locked_until BIGINT,
            consumed_at BIGINT
        )
    """)
    op.execute(
        "CREATE INDEX ix_auth_otp_email_window ON auth_otp_challenges (email, request_window_started)"
    )
    op.execute("""
        CREATE TABLE auth_sessions (
            token_hash CHAR(64) PRIMARY KEY,
            user_id VARCHAR(128) NOT NULL REFERENCES auth_users(id),
            expires_at BIGINT NOT NULL,
            last_activity_at BIGINT NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_auth_sessions_expiry ON auth_sessions (expires_at)")
    op.execute("""
        CREATE TABLE auth_audit_events (
            id BIGSERIAL PRIMARY KEY,
            user_id VARCHAR(128),
            action VARCHAR(128) NOT NULL,
            success BOOLEAN NOT NULL,
            metadata TEXT,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)


def downgrade() -> None:
    op.drop_table("auth_audit_events")
    op.drop_index("ix_auth_sessions_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_auth_otp_email_window", table_name="auth_otp_challenges")
    op.drop_table("auth_otp_challenges")
    op.drop_table("auth_users")
