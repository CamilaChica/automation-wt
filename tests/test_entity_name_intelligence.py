"""Unit tests for entity name intelligence, supplier extraction, and customer name resolution."""

import unittest
from services.entity_name_intelligence import (
    is_generic_mailbox,
    is_garbage_name,
    clean_company_name,
    clean_person_name,
    split_compound_domain,
    derive_company_from_domain,
    extract_company_from_signature,
    name_quality_score,
)
from services.supplier_email_extractor import supplier_email_extractor
from services.orchestration_service import _resolve_best_customer_name
from agents.rfq_intake_agent import RFQIntakeAgent


class EntityNameIntelligenceTests(unittest.TestCase):
    def test_generic_mailbox_detection(self):
        self.assertTrue(is_generic_mailbox("procurement"))
        self.assertTrue(is_generic_mailbox("purchasing@deltamro.com"))
        self.assertTrue(is_generic_mailbox("sales team"))
        self.assertTrue(is_generic_mailbox("Quotes Department"))
        self.assertTrue(is_generic_mailbox("rfq-desk"))
        self.assertTrue(is_generic_mailbox("buyer"))
        self.assertFalse(is_generic_mailbox("John Smith"))
        self.assertFalse(is_generic_mailbox("Apex Aero Components LLC"))

    def test_garbage_and_chatter_filtering(self):
        self.assertTrue(is_garbage_name("Good Afternoon"))
        self.assertTrue(is_garbage_name("Dear Procurement Team"))
        self.assertTrue(is_garbage_name("See attached quote"))
        self.assertTrue(is_garbage_name("acmeaero.com"))
        self.assertTrue(is_garbage_name("Winged Tycoons"))
        self.assertTrue(is_garbage_name("Unknown Supplier"))
        self.assertTrue(is_garbage_name("N/A"))
        self.assertFalse(is_garbage_name("Delta MRO"))
        self.assertFalse(is_garbage_name("Apex Aero Components LLC"))
        self.assertFalse(is_garbage_name("Vanguard Spares"))

    def test_clean_company_name(self):
        self.assertEqual(clean_company_name("apex aero components llc"), "Apex Aero Components LLC")
        self.assertEqual(clean_company_name('"DELTA MRO INC."'), "Delta MRO Inc.")
        self.assertEqual(clean_company_name("wyatt aerospace"), "Wyatt Aerospace")
        self.assertEqual(clean_company_name("  vanguard spares ltd  "), "Vanguard Spares LTD")

    def test_clean_person_name(self):
        self.assertEqual(clean_person_name("John Smith - Procurement Manager"), "John Smith")
        self.assertEqual(clean_person_name("Alice Johnson (Purchasing)"), "Alice Johnson")
        self.assertEqual(clean_person_name("Robert 'Bob' Vance"), "Robert Vance")

    def test_split_compound_domain(self):
        self.assertEqual(split_compound_domain("apexaero"), "Apex Aero")
        self.assertEqual(split_compound_domain("deltamro"), "Delta MRO")
        self.assertEqual(split_compound_domain("wyattaerospace"), "Wyatt Aerospace")
        self.assertEqual(split_compound_domain("vanguardspares"), "Vanguard Spares")

    def test_derive_company_from_domain(self):
        self.assertEqual(derive_company_from_domain("rfq@deltamro.com"), "Delta MRO")
        self.assertEqual(derive_company_from_domain("sales@apexaero.com"), "Apex Aero")
        self.assertEqual(derive_company_from_domain("orders@wyattaerospace.com"), "Wyatt Aerospace")
        # Should not derive from generic consumer email providers
        self.assertEqual(derive_company_from_domain("john@gmail.com"), "")
        self.assertEqual(derive_company_from_domain("sarah@yahoo.com"), "")

    def test_extract_company_from_signature(self):
        body = (
            "Hello,\n\nPlease review our quote.\n\n"
            "Best regards,\n"
            "David Miller\n"
            "Senior Account Director\n"
            "Vanguard Spares & Logistics LLC\n"
            "Tel: +1-555-0199"
        )
        contact, company = extract_company_from_signature(body)
        self.assertEqual(company, "Vanguard Spares & Logistics LLC")
        self.assertEqual(contact, "David Miller")

    def test_name_quality_score(self):
        score_legal = name_quality_score("Apex Aero Components LLC")
        score_compound = name_quality_score("Apex Aero")
        score_single = name_quality_score("Apexaero")
        score_generic = name_quality_score("Sales Team")

        self.assertGreater(score_legal, score_compound)
        self.assertGreater(score_compound, score_single)
        self.assertGreater(score_single, score_generic)

    def test_supplier_extractor_with_uppercase_display_name(self):
        sender = '"APEX AERO COMPONENTS LLC" <quotes@apexaero.com>'
        body = "Hello Winged Tycoons Team,\nHere is the quote you requested.\nPN: 060-0012-00\nPrice: $4500"
        extracted = supplier_email_extractor._extract_supplier_name(sender=sender, body=body)
        self.assertEqual(extracted, "Apex Aero Components LLC")

    def test_supplier_extractor_with_signature(self):
        sender = "quotes@apexaero.com"
        body = (
            "Please find our pricing below.\n\n"
            "Sincerely,\n"
            "Rachel Green\n"
            "Vice President of Sales\n"
            "Apex Aero Components LLC\n"
            "rachel@apexaero.com"
        )
        extracted = supplier_email_extractor._extract_supplier_name(sender=sender, body=body)
        self.assertEqual(extracted, "Apex Aero Components LLC")

    def test_resolve_best_customer_name(self):
        # Initial mailbox name is generic "Procurement", but parsed extracted real company
        best = _resolve_best_customer_name(
            existing_name="Procurement",
            parsed_company="Delta MRO Aerospace",
            parsed_contact="John Doe",
            email="procurement@deltamro.com",
        )
        self.assertEqual(best, "Delta MRO Aerospace")

        # Initial mailbox name is email address
        best = _resolve_best_customer_name(
            existing_name="buyer@wyattaerospace.com",
            parsed_company=None,
            parsed_contact="Alice Smith",
            email="buyer@wyattaerospace.com",
        )
        # Should derive company from domain
        self.assertEqual(best, "Wyatt Aerospace")

    def test_rfq_intake_agent_does_not_confuse_part_name_or_greetings(self):
        from agents.rfq_intake_agent import _extract_customer_info
        text = (
            "From: Sarah Connor <sarah@skyline-aviation.com>\n"
            "Subject: RFQ - Fastener\n\n"
            "Good Afternoon,\n\n"
            "Please quote the following:\n"
            "Part Name: Flange Bracket Assembly\n"
            "Part Number: 10-60124-1\n"
            "Qty: 4\n\n"
            "Thank you,\n"
            "Sarah Connor\n"
            "Skyline Aviation MRO LLC"
        )
        customer_name, company, email = _extract_customer_info(text)
        self.assertNotEqual(customer_name, "Flange Bracket Assembly")
        self.assertNotEqual(company, "Good Afternoon")
        self.assertEqual(customer_name, "Sarah Connor")
        self.assertEqual(company, "Skyline Aviation MRO LLC")


if __name__ == "__main__":
    unittest.main()
