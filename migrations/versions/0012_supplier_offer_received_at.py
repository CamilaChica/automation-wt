"""Track supplier quote age from the original email receipt time."""

from alembic import op
import sqlalchemy as sa


revision = "0012_supplier_offer_received_at"
down_revision = "0011_merge_postgres_migration_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplier_parts",
        sa.Column("source_received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("""
        UPDATE supplier_parts AS offer
        SET source_received_at = (
            SELECT raw.received_at
            FROM raw_emails AS raw
            WHERE raw.mailbox = 'purchasing'
              AND raw.received_at IS NOT NULL
              AND (
                  raw.provider_message_id = split_part(offer.source_email_id, ':', 1)
                  OR raw.internet_message_id = split_part(offer.source_email_id, ':', 1)
              )
            ORDER BY (raw.provider_message_id = split_part(offer.source_email_id, ':', 1)) DESC
            LIMIT 1
        )
        WHERE offer.source_email_id IS NOT NULL
          AND offer.source_received_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column("supplier_parts", "source_received_at")
