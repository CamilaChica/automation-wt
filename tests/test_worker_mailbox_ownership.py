from worker import _mailboxes_to_poll


def test_email_worker_only_polls_sales_mailbox():
    assert _mailboxes_to_poll() == ["sales"]