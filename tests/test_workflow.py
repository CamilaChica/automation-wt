import unittest
import asyncio
from services.db_service import db_service
from services.orchestration_service import orchestration_service

class TestRFQQuoteWorkflow(unittest.TestCase):
    def setUp(self):
        # Reset mock database for clean test isolation
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.seed_mock_data()

    def test_scenario_a_clean_flow(self):
        """
        Scenario A: Request a part that exists in internal inventory with correct traces.
        Expects a straight-through automated run resulting in Quote_Sent.
        """
        async def run_scenario():
            # Submit raw RFQ text
            raw_email = (
                "Hello Sales, please quote: \n"
                "Part Number: 060-1234-00 | Qty: 2 \n"
                "Please deliver ASAP to Delta MRO Services."
            )
            
            # 1. Intake
            rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", raw_email)
            self.assertEqual(rfq.status, "Intake")
            
            # 2. Pipeline Execution
            pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)
            
            # Assertions
            self.assertEqual(pipeline_res["status"], "Quote_Sent")
            quote_id = pipeline_res["quote_id"]
            
            # Verify quote sums (Unit cost = 1000, 20% margin -> Retail = 1250 each. Qty = 2 -> 2500 total)
            quote = db_service.get_quote(quote_id)
            self.assertEqual(quote.subtotal, 2500.0)
            self.assertEqual(quote.status, "Sent")
            
            # Verify logs contain appropriate agent transitions
            logs = db_service.get_audit_logs(rfq.id)
            agents_ran = [log.agent_name for log in logs]
            self.assertIn("RFQIntakeAgent", agents_ran)
            self.assertIn("PartsIntelligenceAgent", agents_ran)
            self.assertIn("InventoryAgent", agents_ran)
            self.assertIn("ComplianceAgent", agents_ran)
            self.assertIn("PricingAgent", agents_ran)
            
            # 3. Legacy approval is idempotent after autonomous dispatch.
            approval_res = await orchestration_service.approve_and_send_quote(quote_id, "John Doe Operator")
            self.assertEqual(approval_res["status"], "Quote_Sent")
            self.assertIn("QTE-", approval_res["quote_id"])
            
            # State transitions complete
            self.assertEqual(db_service.get_rfq(rfq.id).status, "Quote_Sent")
            
        asyncio.run(run_scenario())

    def test_scenario_b_sourcing_fallback(self):
        """
        Scenario B: Request quantities larger than available inventory.
        Expects InventoryAgent stockout escalation -> SupplierDiscoveryAgent activation -> Pricing -> Quote_Sent.
        """
        async def run_scenario():
            # Internal stock has 2 items of 060-1234-00. Let's request 5 items.
            raw_email = "Need part 060-1234-00, quantity 5. Urgent AOG! Contact Delta MRO Services."
            
            rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", raw_email)
            pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)
            
            # Sourcing lookup succeeds and maps supplier spares
            self.assertEqual(pipeline_res["status"], "Quote_Sent")
            quote_id = pipeline_res["quote_id"]
            quote_items = db_service.get_quote_items(quote_id)
            
            # Sourcing fallback verified: sources are a mix of inventory and external supplier
            sources = [i.source for i in quote_items]
            self.assertIn("Supplier", sources)
            
        asyncio.run(run_scenario())

    def test_unknown_part_starts_supplier_outreach(self):
        async def run_scenario():
            raw_email = "Part Number: 999-UNKNOWN-01 | Qty: 2. Please source this item."
            rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", raw_email)

            pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)

            self.assertEqual(pipeline_res["status"], "Supplier_Request_Sent")
            self.assertGreaterEqual(pipeline_res["supplier_request_count"], 0)
            self.assertEqual(db_service.get_rfq(rfq.id).status, "Supplier_Sourcing")
            logs = db_service.get_audit_logs(rfq.id)
            self.assertIn("SupplierCommunicationAgent", [log.agent_name for log in logs])

        asyncio.run(run_scenario())

    def test_scenario_c_compliance_halt(self):
        """
        Scenario C: Part has a compliance exception (e.g. missing trace in inventory).
        Expects ComplianceAgent warning escalation -> Orchestrator halts pipeline at Compliance_Warning state.
        """
        async def run_scenario():
            # 456-789-OH has two items in stock: SN-ACT-981 (FAA trace) and SN-ACT-982 (missing trace)
            # Requesting 2 items forces the utilization of the item missing traceability.
            raw_email = "Requesting: 456-789-OH, Qty: 2. From Delta MRO Services."
            
            rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", raw_email)
            pipeline_res = await orchestration_service.process_rfq_pipeline(rfq.id)
            
            # State halts at Compliance Warning
            self.assertEqual(pipeline_res["status"], "Compliance_Warning")
            self.assertIsNotNone(pipeline_res.get("escalation"))
            
            # Ensure DB RFQ status matches halted state
            updated_rfq = db_service.get_rfq(rfq.id)
            self.assertEqual(updated_rfq.status, "Compliance_Warning")
            
        asyncio.run(run_scenario())

    def test_quote_email_summary_preserves_uom_and_attachments(self):
        quote_id = "QTE-TEST1"
        db_service.quotes[quote_id] = type("QuoteStub", (), {
            "id": quote_id,
            "rfq_id": "RFQ-TEST",
            "subtotal": 2000.0,
            "shipping_cost": 50.0,
            "total_amount": 2050.0,
            "status": "Approved",
            "comments": None,
            "approved_by": None,
            "approved_at": None,
        })()
        db_service.quote_items[quote_id] = [
            type("QuoteItemStub", (), {
                "id": "QITM-1",
                "quote_id": quote_id,
                "rfq_item_id": "RITM-1",
                "part_number": "060-1234-00",
                "quantity": 2,
                "uom": "EA",
                "attachments": ["FAA-8130-3.pdf", "spec-sheet.pdf"],
                "source": "Inventory",
                "unit_cost": 950.0,
                "unit_price": 1000.0,
                "margin_percent": 5.0,
                "certificate_type": "FAA 8130-3",
                "compliance_status": "Pass",
            })()
        ]
        summary = orchestration_service.comm_agent._format_quote_summary({
            "quote_id": quote_id,
            "subtotal": 2000.0,
            "shipping_cost": 50.0,
            "total_amount": 2050.0,
            "items": [
                {
                    "part_number": "060-1234-00",
                    "quantity": 2,
                    "uom": "EA",
                    "unit_price": 1000.0,
                    "attachments": ["FAA-8130-3.pdf", "spec-sheet.pdf"],
                }
            ],
        })

        self.assertIn("Qty 2 EA", summary)
        self.assertIn("Attachments:", summary)
        self.assertIn("FAA-8130-3.pdf", summary)
        self.assertIn("spec-sheet.pdf", summary)

if __name__ == "__main__":
    unittest.main()
