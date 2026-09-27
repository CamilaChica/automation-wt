"""Add employee profiles and append-only time tracking events."""

from alembic import op


revision = "0007_employee_time_tracking"
down_revision = "0006_outbox_manual_review_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE employee_profiles (
            user_id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            display_name VARCHAR(120) NOT NULL,
            job_title VARCHAR(120) NOT NULL,
            is_online BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE employee_time_events (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            email TEXT NOT NULL,
            event_type VARCHAR(32) NOT NULL CHECK (event_type IN (
                'profile_updated', 'presence_online', 'presence_offline', 'clock_in', 'clock_out'
            )),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            details JSONB
        )
    """)
    op.execute("CREATE INDEX ix_employee_time_events_user_time ON employee_time_events (user_id, occurred_at, id)")
    op.execute("CREATE INDEX ix_employee_time_events_email_time ON employee_time_events (email, occurred_at)")


def downgrade() -> None:
    op.drop_index("ix_employee_time_events_email_time", table_name="employee_time_events")
    op.drop_index("ix_employee_time_events_user_time", table_name="employee_time_events")
    op.drop_table("employee_time_events")
    op.drop_table("employee_profiles")