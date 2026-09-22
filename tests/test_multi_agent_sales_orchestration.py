"""Batch evaluation for the first five customer RFQs.

Default mode is deterministic mock mode and still executes the real agents and
orchestrator. Set WT_TEST_MODE=live to run against the configured providers and
catalogs without the deterministic fixtures.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

if os.getenv("WT_TEST_MODE", "mock").strip().lower() == "mock":
    os.environ.setdefault("LLM_LIVE_ENABLED", "false")
    os.environ.setdefault("LLM_ALLOW_TEMPLATE_FALLBACK", "true")
    os.environ.setdefault("EMAIL_SEND_ENABLED", "false")

from agents.compliance_agent import ComplianceAgent
from agents.customer_communication_agent import CustomerCommunicationAgent, GeneratedEmailDraft
from agents.parts_intelligence_agent import PartsIntelligenceAgent
from agents.rfq_intake_agent import RFQIntakeAgent
from data.mock_inventory_db import MOCK_INVENTORY_DB
from models.db_models import RFQIntakeOutput
from services.db_service import db_service
from services.orchestration_service import OrchestrationService
from services.supplier_database import supplier_db
from tools.tool_interfaces import SearchPartsCatalogTool


RFQ_CASES = [
    {
        "name": "routine hardware",
        "raw_text": "From: Routine Hardware Buyer <buyer@routineaero.example>\nCompany: Routine Aero\nPlease quote 50x MS20470AD4-6 rivets, condition NE, required by 2026-10-15.\nDeliver to MIA.",
        "part_number": "MS20470AD4-6",
        "quantity": 50,
        "condition": "NE",
        "priority": "Routine",
        "compliance": {"source": "Supplier", "supplier_name": "Approved Mock Supplier", "certificate_type": "FAA 8130-3", "has_full_trace": True},
    },
    {
        "name": "aog brake assembly",
        "raw_text": "AOG emergency for Global Airlines. Contact aog@global.example. Need 1 main landing gear brake assembly, P/N BRK-3200-OH, condition OH, dual release FAA 8130-3, by 2026-09-23.",
        "part_number": "BRK-3200-OH",
        "quantity": 1,
        "condition": "OH",
        "priority": "AOG",
        "compliance": {"source": "Supplier", "supplier_name": "Approved Mock Supplier", "certificate_type": "FAA 8130-3", "has_full_trace": True, "requested_certificate_type": "FAA 8130-3"},
    },
    {
        "name": "multi-line request",
        "raw_text": "From: Fleet MRO <procurement@fleetmro.example>\nCompany: Fleet MRO\nP/N MS21042-3 qty 4 condition NE needed 2026-10-01; P/N AN960-416 qty 12 condition NE needed 2026-10-05; P/N BACR15CE5D5 qty 8 condition OH needed 2026-10-20.",
        "part_number": "MS21042-3",
        "quantity": 4,
        "condition": "NE",
        "priority": "Routine",
        "minimum_items": 3,
        "compliance": {"source": "Supplier", "supplier_name": "Approved Mock Supplier", "certificate_type": "EASA Form 1", "has_full_trace": True},
    },
    {
        "name": "messy ambiguous aog",
        "raw_text": "AOG / urgent request from Hangar 7 <ops@hangar7.example>. Need one actuator PN ACT-7788-AR. Condition could be NE or OH, please confirm availability and certs.",
        "part_number": "ACT-7788-AR",
        "quantity": 1,
        "condition": "AR",
        "priority": "AOG",
        "expected_intake_review": True,
        "compliance": {"source": "Inventory", "supplier_name": "Winged Tycoons Internal", "certificate_type": "FAA 8130-3", "has_full_trace": False},
    },
    {
        "name": "compliance restricted",
        "raw_text": "From: Defense Systems <trade@defense.example>\nITAR-controlled export-restricted component P/N ITAR-9000-AR, quantity 2, condition AR, requires FAA 8130-3 and complete export trace review.",
        "part_number": "ITAR-9000-AR",
        "quantity": 2,
        "condition": "AR",
        "priority": "Routine",
        "compliance": {"source": "Supplier", "supplier_name": "Sanctioned Export Supplier", "certificate_type": "FAA 8130-3", "has_full_trace": True},
        "expected_compliance": "REJECTED",
    },
]


def _catalog_result(args):
    part_number = args["part_number"].strip().upper()
    return {
        "found": True,
        "match_type": "exact",
        "parts": [{
            "part_number": part_number,
            "description": f"Mock aerospace component {part_number}",
            "manufacturer": "Mock Aerospace",
            "category": "Aerospace Hardware",
            "aircraft_applicability": "Commercial aircraft",
            "condition": "NE",
            "alternate_part_numbers": [],
            "documentation_requirements": ["FAA 8130-3"],
        }],
    }


async def _mock_catalog_run(_tool, args):
    return _catalog_result(args)


def _mock_supplier_offers(part_number, quantity_needed=1):
    return [{
        "supplier_id": "SUP-MOCK",
        "supplier_name": "Approved Mock Supplier",
        "part_number": part_number.upper(),
        "quantity_available": max(int(quantity_needed), 100),
        "unit_cost": 100.0,
        "lead_time_days": 3,
        "certificate_type": "FAA 8130-3",
        "approval_status": "Approved",
        "reliability_score": 98.0,
        "score": 100.0,
    }]


class TestMultiAgentSalesOrchestration(unittest.TestCase):
    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.inventory.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.shipments.clear()
        db_service.shipment_events.clear()
        db_service.seed_mock_data()
        self._seed_supplier_offers()

    def _seed_supplier_offers(self):
        for case in RFQ_CASES:
            supplier_db.save_supplier_offer(
                supplier_name="Approved Mock Supplier",
                supplier_email="quotes@mock-supplier.example",
                part_number=case["part_number"],
                quantity_available=max(case["quantity"], 100),
                unit_cost=100.0,
                certificate_type="FAA 8130-3",
                lead_time_days=3,
                approval_status="Approved",
            )

    async def _run_batch(self):
        intake_agent = RFQIntakeAgent()
        parts_agent = PartsIntelligenceAgent()
        compliance_agent = ComplianceAgent()
        communication_agent = CustomerCommunicationAgent()
        orchestrator = OrchestrationService()
        results = []

        for case in RFQ_CASES:
            intake = await intake_agent.execute({"raw_text": case["raw_text"]})
            self.assertIsNotNone(intake.data)
            structured = RFQIntakeOutput.model_validate(intake.data)
            self.assertTrue(structured.part_number, case["name"])
            self.assertGreaterEqual(structured.quantity or 0, 1, case["name"])
            self.assertIn(structured.priority, {"AOG", "Urgent", "Routine"})
            if case.get("minimum_items"):
                self.assertGreaterEqual(len(intake.data.get("items", [])), case["minimum_items"])
            if case.get("expected_intake_review"):
                self.assertTrue(structured.ambiguous_fields or not intake.success)

            parts = await parts_agent.execute({"requested_part_number": case["part_number"]})
            self.assertTrue(parts.success, parts.error_message)
            self.assertTrue(parts.data["is_valid"])
            self.assertGreaterEqual(parts.data["confidence_score"], 0.0)

            compliance_input = {"part_number": case["part_number"], **case["compliance"]}
            compliance = await compliance_agent.execute(compliance_input)
            self.assertIn(compliance.data["compliance_status"], {"APPROVED", "HUMAN_REVIEW_REQUIRED", "REJECTED"})
            if case.get("expected_compliance"):
                self.assertEqual(compliance.data["compliance_status"], case["expected_compliance"])
            else:
                self.assertIn(compliance.data["compliance_status"], {"APPROVED", "HUMAN_REVIEW_REQUIRED"})

            draft = await communication_agent.execute({
                "customer_email": f"customer-{len(results) + 1}@example.com",
                "customer_name": "Test Customer",
                "quote_details": {
                    "quote_id": f"TEST-QUOTE-{len(results) + 1}",
                    "subtotal": 1250.0,
                    "total_amount": 1250.0,
                    "items": [{
                        "part_number": case["part_number"],
                        "quantity": case["quantity"],
                        "uom": "EA",
                        "unit_price": 1250.0,
                        "lead_time_days": 3,
                    }],
                },
            })
            self.assertTrue(draft.success, draft.error_message)
            body = draft.data["formatted_body"]
            self.assertTrue(body.strip())
            self.assertIn("$1,250.00", body)
            self.assertNotIn("unit_cost", body.lower())
            self.assertNotIn("supplier costs", body.lower())

            customer_email = f"customer-{len(results) + 1}@example.com"
            rfq = db_service.create_rfq("Test Customer", customer_email, case["raw_text"])
            pipeline = await orchestrator.process_rfq_pipeline(rfq.id)
            persisted = db_service.get_rfq(rfq.id)
            self.assertIsNotNone(persisted)
            self.assertIn(persisted.status, {"Quote_Sent", "Pending_Internal_Review"}, f"{case['name']}: {pipeline}")
            self.assertNotEqual(persisted.status, "Intake_Failed")
            results.append(pipeline)

        self.assertEqual(len(results), 5)

    def test_first_five_customer_rfqs_complete_agent_pipeline(self):
        mode = os.getenv("WT_TEST_MODE", "mock").strip().lower()
        if mode == "mock":
            with patch.object(SearchPartsCatalogTool, "run", new=_mock_catalog_run), patch.object(
                supplier_db, "find_supplier_offers", side_effect=_mock_supplier_offers
            ):
                asyncio.run(self._run_batch())
        elif mode == "live":
            asyncio.run(self._run_batch())
        else:
            self.fail("WT_TEST_MODE must be either 'mock' or 'live'.")


if __name__ == "__main__":
    unittest.main()
