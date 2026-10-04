import asyncio
from unittest.mock import patch

import pytest
from unittest.mock import AsyncMock, Mock

from services.communication_service import CommunicationService
from services.mailbox_service import send_message


def test_staging_email_is_blocked_when_recipient_is_not_allowlisted():
    with patch.dict(
        "os.environ",
        {
            "WT_ENV": "staging",
            "ENVIRONMENT": "staging",
            "STAGING_EMAIL_ALLOWLIST": "safe-inbox@example.test",
        },
        clear=False,
    ):
        with pytest.raises(RuntimeError, match="STAGING_EMAIL_ALLOWLIST"):
            CommunicationService()._send(
                "sales",
                "external-customer@example.com",
                "Staging test",
                "Test only",
                reply_to=None,
            )


def test_staging_allowlisted_email_can_be_queued():
    with (
        patch.dict(
            "os.environ",
            {
                "WT_ENV": "staging",
                "ENVIRONMENT": "staging",
                "STAGING_EMAIL_ALLOWLIST": "safe-inbox@example.test",
            },
            clear=False,
        ),
        patch("services.communication_service.operations_store._postgres", object()),
        patch(
            "services.communication_service.operations_store.enqueue_outbox_message",
            return_value={"id": "OUTBOX-STAGING-1", "status": "PENDING"},
        ) as enqueue,
    ):
        result = CommunicationService()._send(
            "sales",
            "SAFE-INBOX@example.test",
            "Staging test",
            "Test only",
            reply_to=None,
        )

    assert result["transmission_status"] == "PENDING"
    enqueue.assert_called_once()


def test_staging_transport_blocks_recipients_outside_allowlist():
    with patch.dict(
        "os.environ",
        {
            "WT_ENV": "production",
            "ENVIRONMENT": "production",
            "STAGING_EMAIL_ALLOWLIST": "safe-inbox@example.test",
        },
        clear=False,
    ):
        with pytest.raises(RuntimeError, match="STAGING_EMAIL_ALLOWLIST"):
            send_message(
                "sales",
                "external-customer@example.com",
                "Staging test",
                "Test only",
            )


def test_staging_customer_quote_outbox_rejects_recipient_before_enqueue():
    repositories = Mock()
    repositories.records.enqueue_outbox_message = AsyncMock()
    service = CommunicationService()

    with patch.dict(
        "os.environ",
        {
            "WT_ENV": "staging",
            "ENVIRONMENT": "staging",
            "STAGING_EMAIL_ALLOWLIST": "safe-inbox@example.test",
        },
        clear=False,
    ):
        with pytest.raises(RuntimeError, match="STAGING_EMAIL_ALLOWLIST"):
            asyncio.run(service.enqueue_customer_quote_async(
                repositories,
                recipient="external-customer@example.com",
                quote_id="QTE-STAGING-1",
                rfq_id="RFQ-STAGING-1",
                subject="Quotation",
                body="Quote details",
                quote_items=[],
            ))

    repositories.records.enqueue_outbox_message.assert_not_awaited()
