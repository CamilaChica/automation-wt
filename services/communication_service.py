"""Natural-language supplier and customer email workflows."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.mailbox_service import send_message
from services.supplier_database import supplier_db


SUPPLIER_QUOTE_FIELDS = (
    "supplier company and contact name",
    "part number and condition code (NE, NS, OH, or AR)",
    "quantity available",
    "unit price and currency",
    "lead time or estimated ship date",
    "release certificate and trace documentation",
    "quote validity or expiration date",
)


class CommunicationService:
    """Coordinates human-readable outbound messages and preserves reply headers."""

    def _sending_enabled(self) -> bool:
        return os.getenv("EMAIL_SEND_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def request_part_quotes(self, part_number: str, quantity: int, reply_to: Optional[str] = None) -> List[Dict[str, Any]]:
        recipients = [supplier.get("email") for supplier in supplier_db.list_suppliers() if supplier.get("email")]
        configured = os.getenv("SUPPLIER_REQUEST_RECIPIENTS", "")
        recipients.extend(address.strip() for address in configured.split(",") if address.strip())
        recipients = list(dict.fromkeys(recipients))
        subject = f"RFQ request: {part_number.upper()} - {quantity} EA"
        body = self._supplier_quote_request(part_number, quantity)
        results = []
        for recipient in recipients:
            results.append(self._send("purchasing", recipient, subject, body, reply_to=reply_to))
        return results

    def request_missing_supplier_fields(
        self,
        recipient: str,
        part_number: str,
        missing_fields: List[str],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = f"Re: RFQ request: {part_number.upper()} - information needed"
        body = self._missing_fields_request(part_number, missing_fields)
        return self._send("purchasing", recipient, subject, body, reply_to=reply_to)

    def notify_purchase_order(
        self,
        recipient: str,
        po_number: str,
        customer_name: str,
        customer_email: str,
        quote_id: str,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        item_lines = []
        for item in items:
            item_lines.append(
                f"- {item['part_number']} | Qty {item['quantity']} | Customer price ${item['unit_price']:,.2f} | "
                f"Selected supplier: {item.get('supplier_name', 'Internal inventory')} | "
                f"Supplier cost: ${item.get('supplier_unit_cost', 0.0):,.2f}"
            )
        body = (
            f"Purchase order received: {po_number}\n\n"
            f"Customer: {customer_name}\nCustomer email: {customer_email}\nQuote: {quote_id}\n\n"
            "Requested items:\n" + "\n".join(item_lines) + "\n\n"
            "Please take over the human purchasing and supplier-confirmation process. "
            "Supplier details are included for internal use only."
        )
        return self._send(
            "sales",
            recipient,
            f"PURCHASE ORDER {po_number} - human purchasing review",
            body,
            reply_to=None,
        )

    def send_shipment_tracking_link(self, recipient: str, shipment_id: str, public_token: str) -> Dict[str, Any]:
        portal_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3000")
        tracking_url = f"{portal_url.rstrip('/')}/track/{public_token}"
        body = (
            "Hello,\n\n"
            f"Your Winged Tycoons shipment {shipment_id} is now being prepared. "
            "You can follow its status using this private tracking link:\n\n"
            f"{tracking_url}\n\n"
            "The tracking page will show carrier updates, latest location, and estimated delivery when available.\n\n"
            "Kind regards,\nWinged Tycoons Logistics Team"
        )
        return self._send(
            "sales",
            recipient,
            f"Shipment tracking available - {shipment_id}",
            body,
            reply_to=None,
        )

    def request_supplier_availability_confirmation(
        self,
        recipient: str,
        supplier_name: str,
        po_number: str,
        items: List[Dict[str, Any]],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        item_lines = "\n".join(
            f"- {item['part_number']} | Qty {item['quantity']} | Previously quoted ${item['supplier_unit_cost']:,.2f} each"
            for item in items
        )
        body = (
            f"Hello {supplier_name},\n\n"
            f"Our customer has issued purchase order {po_number}. Before we proceed, please confirm in this same "
            "email thread that the following quoted material is still available and that the quoted commercial and "
            "documentation terms remain valid:\n\n"
            f"{item_lines}\n\n"
            "Please confirm quantity available, condition, release certificate/trace, price, and estimated ship date. "
            "Do not ship until we provide written authorization.\n\n"
            "Kind regards,\nWinged Tycoons Purchasing Team"
        )
        return self._send(
            "purchasing",
            recipient,
            f"Re: Purchase order {po_number} - availability confirmation",
            body,
            reply_to=reply_to,
        )

    def send_customer_quote(
        self,
        recipient: str,
        customer_name: str,
        quote_id: str,
        quote_summary: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = f"Winged Tycoons quotation {quote_id}"
        body = (
            f"Dear {customer_name},\n\n"
            "Thank you for your request. Please find the approved quotation below.\n\n"
            f"{quote_summary}\n\n"
            "To proceed, reply to this email with your purchase order or any questions. "
            "We will keep this conversation together for follow-up.\n\n"
            "Best regards,\nWinged Tycoons Sales Team"
        )
        result = self._send("sales", recipient, subject, body, reply_to=reply_to)
        self.schedule_customer_followup(
            recipient=recipient,
            customer_name=customer_name,
            quote_id=quote_id,
            reply_to=reply_to,
        )
        return result

    def schedule_customer_followup(
        self,
        recipient: str,
        customer_name: str,
        quote_id: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        delay_minutes = int(os.getenv("CUSTOMER_FOLLOWUP_DELAY_MINUTES", "30"))
        now = datetime.now(timezone.utc)
        due = now + timedelta(minutes=delay_minutes)
        if due.date() != now.date():
            return {
                "task_key": f"customer-followup:{quote_id}",
                "task_type": "customer_followup",
                "status": "SKIPPED_OUTSIDE_SAME_DAY",
            }
        due_at = due.isoformat()
        subject = f"Re: Winged Tycoons quotation {quote_id}"
        body = (
            f"Hello {customer_name},\n\n"
            f"I wanted to make sure our quotation {quote_id} reached you and that you have everything needed "
            "to review it. We would be glad to answer questions about availability, certification, delivery, "
            "or commercial terms.\n\n"
            "If the requirement is still active, simply reply here and we will keep the quoted material reserved "
            "subject to availability.\n\n"
            "Kind regards,\nWinged Tycoons Sales Team"
        )
        return supplier_db.schedule_communication_task(
            task_key=f"customer-followup:{quote_id}",
            task_type="customer_followup",
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            due_at=due_at,
            reply_to=reply_to,
        )

    def schedule_supplier_discount_request(
        self,
        recipient: str,
        supplier_name: str,
        part_number: str,
        unit_cost: float,
        source_email_id: str,
        reply_to: Optional[str] = None,
        round_number: int = 1,
    ) -> Dict[str, Any]:
        max_rounds = int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "2"))
        if round_number > max_rounds:
            return {"status": "LIMIT_REACHED", "round": round_number}
        subject = f"Re: Quote for {part_number.upper()} - commercial review"
        body = (
            f"Hello {supplier_name},\n\n"
            f"Thank you for quoting part {part_number.upper()} at ${unit_cost:,.2f} each. "
            "Before we finalize our recommendation, could you please review this once more and share your "
            "best possible net price for the requested quantity?\n\n"
            "If there is a quantity break, prepaid option, core-credit condition, or other commercial adjustment "
            "that would improve the offer, please include it. Please keep the certification, trace, condition, "
            "availability, and delivery terms unchanged unless clearly stated.\n\n"
            "We appreciate your help and will give your revised offer prompt consideration.\n\n"
            "Kind regards,\nWinged Tycoons Purchasing Team"
        )
        return supplier_db.schedule_communication_task(
            task_key=f"supplier-discount:{source_email_id}:{round_number}",
            task_type="supplier_discount_request",
            mailbox="purchasing",
            recipient=recipient,
            subject=subject,
            body=body,
            due_at=datetime.now(timezone.utc).isoformat(),
            reply_to=reply_to,
        )

    def process_due_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        result = self._send(
            task["mailbox"],
            task["recipient"],
            task["subject"],
            task["body"],
            reply_to=task.get("reply_to"),
        )
        return result

    def _send(self, mailbox: str, recipient: str, subject: str, body: str, reply_to: Optional[str]) -> Dict[str, Any]:
        result = {
            "mailbox": mailbox,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "reply_to": reply_to,
            "transmission_status": "DRY_RUN",
        }
        if self._sending_enabled():
            send_message(mailbox, recipient, subject, body, reply_to=reply_to)
            result["transmission_status"] = "SENT"
        return result

    def _supplier_quote_request(self, part_number: str, quantity: int) -> str:
        fields = "\n".join(f"- {field}" for field in SUPPLIER_QUOTE_FIELDS)
        return (
            "Hello,\n\n"
            "We are sourcing the following aircraft part and would appreciate your quotation:\n"
            f"Part number: {part_number.upper()}\n"
            f"Quantity required: {quantity} EA\n\n"
            "Please reply in this email thread with the following information and attach the applicable release "
            "certificate, trace paperwork, and any shop or warranty report:\n"
            f"{fields}\n\n"
            "Please also confirm whether the quoted material is in stock and whether the price includes packing, "
            "handling, or other charges. Thank you.\n\n"
            "Best regards,\nWinged Tycoons Purchasing Team"
        )

    def _missing_fields_request(self, part_number: str, missing_fields: List[str]) -> str:
        requested = "\n".join(f"- {field}" for field in missing_fields)
        return (
            "Hello,\n\n"
            f"Thank you for your quotation for part {part_number.upper()}. To complete our supplier record and "
            "continue the customer quote, could you please reply in this same email thread with:\n"
            f"{requested}\n\n"
            "If a certificate, trace document, or shop report is available, please attach it to your reply. "
            "We will update the offer as soon as the information is received.\n\n"
            "Best regards,\nWinged Tycoons Purchasing Team"
        )


communication_service = CommunicationService()
