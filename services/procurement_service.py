from __future__ import annotations

import json
from typing import Any, Callable

from services.ai_router import AIRouter
from services.db_service import MockDatabaseService, db_service
from services.mailbox_service import send_message


class ProcurementService:
    def __init__(
        self,
        *,
        ai_router: AIRouter | None = None,
        database: MockDatabaseService | None = None,
        email_sender: Callable[[str, str, str, str, str | None], None] | None = None,
    ):
        self.ai_router = ai_router or AIRouter()
        self.database = database or db_service
        self.email_sender = email_sender or send_message

    def trigger_out_of_stock_procurement(self, rfq_id: str, max_suppliers: int = 2) -> list[dict[str, Any]]:
        rfq = self.database.get_rfq(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ '{rfq_id}' not found")

        results: list[dict[str, Any]] = []
        items = self.database.get_rfq_items(rfq_id)
        for item in items:
            part_number = item.resolved_part_number or item.requested_part_number
            requested_qty = item.quantity
            available_qty = self.database.get_available_quantity(part_number, item.condition_preference)
            shortage = max(requested_qty - available_qty, 0)
            if shortage == 0:
                continue

            for supplier in self._select_suppliers(max_suppliers):
                draft = self.ai_router.draft_supplier_rfq(
                    {
                        "rfq_id": rfq_id,
                        "rfq_item_id": item.id,
                        "part_number": part_number,
                        "quantity": shortage,
                        "condition": item.condition_preference or "NE",
                    }
                )
                subject = draft["result"].get("subject") or f"RFQ Request - {part_number}"
                body = draft["result"].get("body") or "Please send quote details."
                recipient = supplier.email_quotes or supplier.email
                self.email_sender("purchasing", recipient, subject, body, None)

                supplier_quote = self.database.create_supplier_quote_request(
                    rfq_item_id=item.id,
                    supplier_id=supplier.id,
                    supplier_name=supplier.company_name,
                    contact_email=recipient,
                    part_number=part_number,
                    quantity_available=shortage,
                    status="PENDING_SUPPLIER_RESPONSE",
                )

                self.database.add_audit_log(
                    rfq_id=rfq_id,
                    agent_name="ProcurementService",
                    action="supplier_outreach",
                    message=f"Sent procurement RFQ to {recipient} for {part_number} x{shortage}",
                    status="SUCCESS",
                    payload=json.dumps(
                        {
                            "supplier_quote_id": supplier_quote.id,
                            "provider": draft["provider"],
                            "model": draft["model"],
                            "fallback_used": draft["fallback_used"],
                        }
                    ),
                )

                results.append(
                    {
                        "rfq_item_id": item.id,
                        "supplier_quote_id": supplier_quote.id,
                        "supplier_id": supplier.id,
                        "recipient": recipient,
                        "part_number": part_number,
                        "shortage_quantity": shortage,
                        "status": supplier_quote.status,
                    }
                )
        return results

    def get_pending_procurement_items(self) -> list[dict[str, Any]]:
        return [
            {
                "supplier_quote_id": quote.id,
                "rfq_item_id": quote.rfq_item_id,
                "supplier_id": quote.supplier_id,
                "supplier_name": quote.supplier_name,
                "contact_email": quote.contact_email,
                "part_number": quote.part_number,
                "status": quote.status,
            }
            for quote in self.database.list_pending_supplier_quotes()
        ]

    def _select_suppliers(self, max_suppliers: int) -> list[Any]:
        approved = [supplier for supplier in self.database.suppliers.values() if supplier.approval_status == "Approved"]
        if not approved:
            return []
        return approved[: max(1, max_suppliers)]


procurement_service = ProcurementService()
