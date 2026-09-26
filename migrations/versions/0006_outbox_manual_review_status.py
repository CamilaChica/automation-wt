"""Allow explicit manual-review status for ambiguous outbox delivery."""

from alembic import op
import sqlalchemy as sa


revision = "0006_outbox_manual_review_status"
down_revision = "0005_operations_store_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "outbox_messages",
        "status",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=False,
        existing_server_default="PENDING",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM outbox_messages WHERE length(status) > 16) THEN "
        "RAISE EXCEPTION 'Cannot downgrade outbox status while values exceed 16 characters'; "
        "END IF; END $$"
    )
    op.alter_column(
        "outbox_messages",
        "status",
        existing_type=sa.String(32),
        type_=sa.String(16),
        existing_nullable=False,
        existing_server_default="PENDING",
    )