import unittest

from services.db_service import db_service


class TestOptimisticConcurrency(unittest.TestCase):
    def test_stale_rfq_status_update_is_rejected(self):
        rfq = db_service.create_rfq("Concurrency Buyer", "concurrency@example.com", "Need XYZ123")
        version = rfq.version
        db_service.update_rfq_status(rfq.id, "Validating", expected_version=version)

        with self.assertRaisesRegex(ValueError, "updated by another"):
            db_service.update_rfq_status(rfq.id, "Supplier_Sourcing", expected_version=version)

    def test_stale_quote_update_is_rejected(self):
        rfq = db_service.create_rfq("Quote Buyer", "quote-concurrency@example.com", "Need XYZ123")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        version = quote.version
        db_service.update_quote_status(quote.id, "Approved", approved_by="operator", expected_version=version)

        with self.assertRaisesRegex(ValueError, "updated by another"):
            db_service.update_quote_status(quote.id, "Rejected", expected_version=version)


if __name__ == "__main__":
    unittest.main()