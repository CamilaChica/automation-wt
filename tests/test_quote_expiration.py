import unittest

from services.db_service import db_service


class TestQuoteExpiration(unittest.TestCase):
    def test_expired_quote_is_marked_expired_on_read(self):
        rfq = db_service.create_rfq("Expiry Buyer", "expiry@example.com", "Need XYZ123")
        quote = db_service.create_quote(
            rfq_id=rfq.id,
            subtotal=100.0,
            shipping=0.0,
            total=100.0,
            valid_until="2000-01-01",
        )
        db_service.update_quote_status(quote.id, "Sent")

        refreshed = db_service.get_quote(quote.id)

        self.assertEqual(refreshed.status, "Expired")


if __name__ == "__main__":
    unittest.main()