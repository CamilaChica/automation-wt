import unittest

from services.document_parser import build_email_context


class DocumentParserTests(unittest.TestCase):
    def test_text_attachment_is_added_to_llm_context(self):
        context = build_email_context(
            "Supplier email body",
            [{"filename": "quote.txt", "content_type": "text/plain", "content": b"Part 5-89356-42 price $2400"}],
        )
        self.assertIn("Supplier email body", context)
        self.assertIn("5-89356-42", context)


if __name__ == "__main__":
    unittest.main()