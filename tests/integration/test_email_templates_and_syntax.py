"""Deterministic structural tests for all outbound email blueprints."""

from __future__ import annotations

import re
import unittest

from services.email_templates import (
    CustomerFollowupData,
    CustomerQuoteData,
    SupplierDiscountData,
    SupplierRFQData,
    SupplierVerificationData,
    customer_followup,
    customer_quote,
    supplier_discount_request,
    supplier_rfq,
    supplier_verification,
)


BANNED_PHRASES = (
    "as an ai language model",
    "as an ai",
    "dear valued customer",
    "here is your draft",
    "kind manual response",
)


class EmailTemplateAssertions(unittest.TestCase):
    def assert_no_unrendered_placeholders(self, text: str):
        self.assertNotRegex(text, r"[{}]", "Email contains an unrendered template placeholder")
        self.assertNotIn("undefined", text.lower())
        self.assertNotIn("none", text.lower())
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, text.lower(), f"Banned robotic phrase found: {phrase}")

    def assert_professional_layout(self, payload, *, max_words: int | None = None):
        self.assertTrue(payload.subject.strip())
        self.assertTrue(payload.body.strip())
        self.assertRegex(payload.body, r"^(Dear|Hi) .+,\n\n")
        self.assertTrue(
            "Best regards" in payload.body or "Team | Winged Tycoons" in payload.body,
            "Email does not contain an approved professional signature",
        )
        self.assert_no_unrendered_placeholders(payload.subject + "\n" + payload.body)
        if max_words is not None:
            self.assertLess(len(re.findall(r"\b\w+[\w'-]*\b", payload.body)), max_words)


class TestCustomerQuotationTemplate(EmailTemplateAssertions):
    def test_customer_quote_matches_blueprint_and_database_values(self):
        payload = customer_quote(CustomerQuoteData(
            contact_name="Maria Buyer",
            recipient_email="buyer@example.com",
            quote_number="QTE-9921",
            part_number="XYZ123",
            description="Landing gear actuator",
            quantity=2,
            condition="Overhauled",
            certification="FAA Form 8130-3",
            unit_price=4600.0,
            lead_time="5 days",
            valid_until="2026-10-15",
            uom="EA",
            attachments=["FAA-8130-3.pdf", "spec-sheet.pdf"],
        ))

        self.assertEqual(payload.message_type, "CUSTOMER_QUOTE")
        self.assertEqual(payload.subject, "Quotation QTE-9921 - Part Number XYZ123")
        self.assertIn("- Part Number: XYZ123", payload.body)
        self.assertIn("- Quantity: 2 EA", payload.body)
        self.assertIn("- Unit Price: $4,600.00 USD", payload.body)
        self.assertIn("- Attachments: FAA-8130-3.pdf, spec-sheet.pdf", payload.body)
        self.assertIn("- Quote Validity: Valid until 2026-10-15", payload.body)
        self.assert_professional_layout(payload, max_words=150)


class TestSupplierRFQTemplate(EmailTemplateAssertions):
    def test_supplier_rfq_contains_all_required_commercial_questions(self):
        payload = supplier_rfq(SupplierRFQData(
            supplier_contact="John Supplier",
            recipient_email="quotes@example.com",
            part_number="XYZ123",
            quantity=2,
            condition_requested="Serviceable",
            certification_requested="EASA Form 1",
        ))

        self.assertEqual(payload.message_type, "SUPPLIER_RFQ")
        self.assertEqual(payload.subject, "RFQ - PN XYZ123 - Qty 2")
        self.assertRegex(payload.body, r"1\. Unit Price \(USD\)")
        self.assertRegex(payload.body, r"2\. Available Quantity")
        self.assertRegex(payload.body, r"3\. Condition & Traceability/Certification")
        self.assertRegex(payload.body, r"4\. Lead Time & Shipping Location")
        self.assertRegex(payload.body, r"5\. Quote Expiration Date")
        self.assert_professional_layout(payload)


class TestSupplierDiscountTemplate(EmailTemplateAssertions):
    def test_discount_request_uses_exact_original_supplier_price(self):
        payload = supplier_discount_request(SupplierDiscountData(
            supplier_contact="John Supplier",
            recipient_email="quotes@example.com",
            part_number="XYZ123",
            quantity=2,
            quoted_price=3750.0,
        ))

        self.assertEqual(payload.message_type, "SUPPLIER_DISCOUNT_REQUEST")
        self.assertEqual(payload.subject, "Commercial Request - PN XYZ123 (Qty: 2)")
        self.assertIn("PN XYZ123 at $3,750.00 per unit", payload.body)
        self.assertIn("best commercial price", payload.body.lower())
        self.assert_professional_layout(payload)


class TestSupplierVerificationTemplate(EmailTemplateAssertions):
    def test_verification_subject_starts_with_required_urgent_prefix(self):
        payload = supplier_verification(SupplierVerificationData(
            supplier_contact="John Supplier",
            recipient_email="quotes@example.com",
            part_number="XYZ123",
            quantity=2,
            po_number="PO-1001",
        ))

        self.assertEqual(payload.message_type, "SUPPLIER_VERIFICATION")
        self.assertTrue(payload.subject.startswith("URGENT - Availability Confirmation Required"))
        self.assertIn("(PO-1001)", payload.body)
        self.assertIn("- Quantity: 2", payload.body)
        self.assertRegex(payload.body, r"1\. The units are currently in stock")
        self.assertRegex(payload.body, r"2\. The quoted price and condition remain valid")
        self.assertRegex(payload.body, r"3\. The requested airworthiness certification is ready")
        self.assert_professional_layout(payload)


class TestCustomerFollowupTemplate(EmailTemplateAssertions):
    def test_followup_is_short_low_pressure_and_grounded(self):
        payload = customer_followup(CustomerFollowupData(
            contact_name="Maria Buyer",
            recipient_email="buyer@example.com",
            part_number="XYZ123",
            quote_number="QTE-9921",
        ))

        self.assertEqual(payload.message_type, "CUSTOMER_FOLLOWUP")
        self.assertEqual(payload.subject, "Following up on Quote QTE-9921 - PN XYZ123")
        self.assertLess(len(re.findall(r"\b\w+[\w'-]*\b", payload.body)), 80)
        self.assertIn("Please let us know", payload.body)
        self.assertNotRegex(payload.body, re.compile(r"buy now|act immediately|last chance", re.I))
        self.assert_professional_layout(payload, max_words=80)


class TestEmailTemplateTypingAndSafety(unittest.TestCase):
    def test_numeric_fields_are_typed_and_formatted(self):
        payload = customer_quote(CustomerQuoteData(
            contact_name="Buyer",
            recipient_email="buyer@example.com",
            quote_number="QTE-1",
            part_number="XYZ123",
            description="Part",
            quantity=2,
            condition="New",
            certification="CoC",
            unit_price=12.5,
            lead_time="3 days",
            valid_until="2026-10-01",
        ))

        self.assertRegex(payload.body, r"Quantity: 2\b")
        self.assertIn("$12.50 USD", payload.body)
        self.assertNotIn("$12.5 USD", payload.body)

    def test_invalid_numeric_fields_fail_before_composition(self):
        with self.assertRaises(ValueError):
            SupplierRFQData(
                supplier_contact="Supplier",
                recipient_email="supplier@example.com",
                part_number="XYZ123",
                quantity=0,
                condition_requested="New",
                certification_requested="CoC",
            )

    def test_recipient_is_preserved_as_transport_metadata(self):
        payload = customer_followup(CustomerFollowupData(
            contact_name="Buyer",
            recipient_email="buyer@example.com",
            part_number="XYZ123",
            quote_number="QTE-1",
        ))

        self.assertEqual(payload.recipient_email, "buyer@example.com")
        self.assertNotIn("recipient_email", payload.body)


if __name__ == "__main__":
    unittest.main()
