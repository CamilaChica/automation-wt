"""Add PostgreSQL operator-review and LLM telemetry persistence."""

from alembic import op
import sqlalchemy as sa

revision = "0004_review_telemetry_postgres"
down_revision = "0003_shared_operational_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_review_queue",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("task", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("entity_id", sa.String(128)),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("extraction_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("hold_flags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("decision", sa.String(16)),
        sa.Column("decision_by", sa.String(320)),
        sa.Column("decision_payload", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_operator_review_queue_status_created", "operator_review_queue", ["status", "created_at"])
    op.create_index("ix_operator_review_queue_entity", "operator_review_queue", ["entity_id"])
    op.create_index("ix_operator_review_queue_task", "operator_review_queue", ["task"])

    op.create_table(
        "llm_telemetry",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("model_calls_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("validation_result", sa.String(64), nullable=False),
        sa.Column("operator_review_outcome", sa.String(32)),
        sa.Column("review_queue_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_llm_telemetry_task_created", "llm_telemetry", ["task", "created_at"])
    op.create_index("ix_llm_telemetry_review_queue", "llm_telemetry", ["review_queue_id"])

    op.create_table(
        "automation_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("execution_time", sa.DateTime(timezone=True)),
        sa.Column("result", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_automation_events_status_created", "automation_events", ["status", "created_at"])
    op.create_index("ix_automation_events_entity", "automation_events", ["entity_type", "entity_id"])

    op.create_table(
        "carrier_webhook_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "operations_state",
        sa.Column("state_key", sa.String(64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("operations_state")
    op.drop_table("carrier_webhook_events")
    op.drop_index("ix_automation_events_entity", table_name="automation_events")
    op.drop_index("ix_automation_events_status_created", table_name="automation_events")
    op.drop_table("automation_events")
    op.drop_index("ix_llm_telemetry_review_queue", table_name="llm_telemetry")
    op.drop_index("ix_llm_telemetry_task_created", table_name="llm_telemetry")
    op.drop_table("llm_telemetry")
    op.drop_index("ix_operator_review_queue_task", table_name="operator_review_queue")
    op.drop_index("ix_operator_review_queue_entity", table_name="operator_review_queue")
    op.drop_index("ix_operator_review_queue_status_created", table_name="operator_review_queue")
    op.drop_table("operator_review_queue")
