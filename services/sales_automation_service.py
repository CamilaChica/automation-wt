from __future__ import annotations

import json
from typing import Any, Callable

from config.settings import settings
from services.ai_router import AIRouter
from services.db_service import MockDatabaseService, db_service
from services.mailbox_service import send_message


class SalesAutomationService:
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

    def generate_customer_quote(self, rfq_id: str) -> dict[str, Any]:
        rfq = self.database.get_rfq(rfq_id)
        if not rfq:
            raise ValueError(f"RFQ '{rfq_id}' not found")

        items = self.database.get_rfq_items(rfq_id)
        if not items:
            raise ValueError(f"RFQ '{rfq_id}' has no items")

        subtotal = 0.0
        line_items: list[dict[str, Any]] = []
        compliance_verdicts: list[bool] = []
        for item in items:
            part_number = item.resolved_part_number or item.requested_part_number
            unit_cost = None
            source = "Inventory"
            certificate_type = "Unknown"
            has_full_trace = True

            inventory_candidates = self.database.get_inventory_items_for_part(part_number, item.condition_preference)
            if inventory_candidates:
                best_inventory = min(inventory_candidates, key=lambda inv: inv.unit_cost)
                unit_cost = best_inventory.unit_cost
                certificate_type = best_inventory.certificate_type
                has_full_trace = best_inventory.has_full_trace
            else:
                supplier_quotes = self.database.get_supplier_quotes_for_part(part_number, include_pending=False)
                if not supplier_quotes:
                    raise ValueError(f"No inventory or supplier quotes available for part '{part_number}'")
                best_supplier_quote = min(supplier_quotes, key=lambda quote: quote.unit_cost)
                unit_cost = best_supplier_quote.unit_cost
                source = "Supplier"
                certificate_type = best_supplier_quote.certificate_type
                has_full_trace = True

            unit_price = round(unit_cost * (1.0 + settings.target_margin), 2)
            line_total = unit_price * item.quantity
            subtotal += line_total
            compliance = self.ai_router.verify_compliance(
                {
                    "part_number": part_number,
                    "certificate_type": certificate_type,
                    "has_full_trace": has_full_trace,
                    "source": source,
                }
            )
            compliant = bool(compliance["result"].get("compliant")) and has_full_trace
            compliance_verdicts.append(compliant)
            margin_percent = round((unit_price - unit_cost) / unit_price * 100, 2)
            line_items.append(
                {
                    "rfq_item_id": item.id,
                    "part_number": part_number,
                    "quantity": item.quantity,
                    "source": source,
                    "unit_cost": unit_cost,
                    "unit_price": unit_price,
                    "margin_percent": margin_percent,
                    "certificate_type": certificate_type,
                    "compliance_pass": compliant,
                }
            )

        quote = self.database.create_quote(rfq_id=rfq_id, subtotal=round(subtotal, 2), shipping=0.0, total=round(subtotal, 2))
        for line in line_items:
            self.database.add_quote_item(
                quote_id=quote.id,
                rfq_item_id=line["rfq_item_id"],
                part_number=line["part_number"],
                qty=line["quantity"],
                source=line["source"],
                unit_cost=line["unit_cost"],
                unit_price=line["unit_price"],
                margin=line["margin_percent"],
                cert=line["certificate_type"],
                comp_status="Pass" if line["compliance_pass"] else "Warn",
            )

        email_draft = self.ai_router.draft_sales_email(
            {
                "rfq_id": rfq_id,
                "customer_name": rfq.customer_name,
                "part_number": ", ".join(line["part_number"] for line in line_items),
                "line_items": line_items,
                "total_amount": quote.total_amount,
            }
        )

        self.database.update_rfq_status(rfq_id, "Quoted")
        average_margin_decimal = (
            sum(((line["unit_price"] - line["unit_cost"]) / line["unit_price"]) for line in line_items) / len(line_items)
            if line_items
            else 0.0
        )
        can_auto_send = (
            all(compliance_verdicts)
            and average_margin_decimal >= settings.auto_send_min_margin_threshold
            and quote.total_amount <= settings.auto_send_max_total_usd
        )
        approval_required = not can_auto_send
        if can_auto_send:
            subject = email_draft["result"].get("subject") or f"Quote {quote.id}"
            body = email_draft["result"].get("body") or "Please review attached quote details."
            self.email_sender("sales", rfq.customer_email, subject, body, None)
            self.database.update_quote_status(quote.id, "Sent")
            self.database.update_rfq_status(rfq_id, "PO Pending")

        self.database.add_audit_log(
            rfq_id=rfq_id,
            agent_name="SalesAutomationService",
            action="quote_generation",
            message=f"Generated quote {quote.id} for RFQ {rfq_id}",
            status="SUCCESS",
            payload=json.dumps(
                {
                    "quote_id": quote.id,
                    "provider": email_draft["provider"],
                    "model": email_draft["model"],
                    "fallback_used": email_draft["fallback_used"],
                    "auto_send": can_auto_send,
                    "approval_required": approval_required,
                }
            ),
        )

        return {
            "rfq_id": rfq_id,
            "quote_id": quote.id,
            "status": "PO Pending" if can_auto_send else "Quoted",
            "approval_required": approval_required,
            "auto_sent": can_auto_send,
            "email_draft": email_draft["result"],
        }

    def advance_rfq_status(self, rfq_id: str, status: str) -> dict[str, str]:
        allowed = {"Intake", "Quoted", "PO Pending", "Solved"}
        if status not in allowed:
            raise ValueError(f"Unsupported status transition target '{status}'")
        rfq = self.database.update_rfq_status(rfq_id, status)
        if not rfq:
            raise ValueError(f"RFQ '{rfq_id}' not found")
        return {"rfq_id": rfq_id, "status": rfq.status}


sales_automation_service = SalesAutomationService()
