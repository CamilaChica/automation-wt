"""Natural-language supplier and customer email workflows."""

import os
import re
import json
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from services.db_service import db_service
from services.email_context import safe_display_text
from services.email_templates import (
    CustomerFollowupData,
    CustomerQuoteData,
    SupplierDiscountData,
    SupplierRFQData,
    SupplierVerificationData,
    customer_followup as compose_customer_followup,
    customer_quote as compose_customer_quote,
    supplier_discount_request as compose_supplier_discount_request,
    supplier_rfq as compose_supplier_rfq,
    supplier_verification as compose_supplier_verification,
)
from services.mailbox_service import MAILBOXES, send_message
from services.operations_store import operations_store
from services.supplier_database import supplier_db


class PartItem(BaseModel):
    part_number: str = Field(..., min_length=1)
    description: str = Field(..., min_length=3)
    quantity: int = Field(..., gt=0)
    unit_price: Optional[float] = Field(default=None, ge=0.0)

    @field_validator("part_number", "description")
    @classmethod
    def prevent_blank_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned


class EmailPayload(BaseModel):
    recipient_email: str = Field(..., description="Target supplier or customer email")
    subject: str = Field(..., min_length=5)
    rfq_id: str = Field(..., min_length=1)
    parts: List[PartItem] = Field(..., min_items=1)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient_email(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned):
            raise ValueError("Recipient email is invalid.")
        return cleaned

    @field_validator("parts")
    @classmethod
    def validate_parts_list(cls, parts: List[PartItem]) -> List[PartItem]:
        if not parts:
            raise ValueError("Email payload must contain at least one valid part record from SQL.")
        return parts


def prepare_and_validate_email(
    rfq_id: str,
    recipient_email: str,
    subject: str,
    part_rows: List[Dict[str, Any]],
) -> Optional[EmailPayload]:
    raw_sql_data = {
        "recipient_email": recipient_email,
        "subject": subject,
        "rfq_id": rfq_id,
        "parts": [
            {
                "part_number": str(item.get("part_number") or item.get("requested_part_number") or "").strip(),
                "description": str(item.get("description") or item.get("resolved_part_number") or item.get("part_number") or "").strip(),
                "quantity": int(item.get("quantity") or 0),
                "unit_price": item.get("unit_price"),
            }
            for item in part_rows
        ],
    }

    try:
        return EmailPayload(**raw_sql_data)
    except ValidationError as exc:
        raise ValueError(f"CRITICAL: SQL data validation failed for RFQ {rfq_id}. Email aborted. {exc.errors()}") from exc


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

    @staticmethod
    def _parse_sequence_number(prefix: str, value: str) -> Optional[int]:
        if not value:
            return None
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", str(value).strip(), flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _is_valid_email(value: str) -> bool:
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(value or "").strip()))

    def validate_purchase_order_metadata(
        self,
        po_number: str,
        customer_email: str,
        quote_id: str,
        previous_po_number: Optional[str] = None,
        previous_quote_id: Optional[str] = None,
    ) -> None:
        if not po_number or not str(po_number).strip():
            raise ValueError("Purchase order number is missing.")
        if not self._is_valid_email(customer_email):
            raise ValueError("Customer email is invalid.")
        if not quote_id or not str(quote_id).strip():
            raise ValueError("Quote ID is missing.")

        current_po_number = str(po_number).strip()
        current_quote_id = str(quote_id).strip()

        if self._parse_sequence_number("PO", current_po_number) is None:
            raise ValueError("Purchase order number must match the format PO-####.")
        if self._parse_sequence_number("QTE", current_quote_id) is None:
            raise ValueError("Quote ID must match the format QTE-####.")

        if previous_po_number:
            prev_po = self._parse_sequence_number("PO", str(previous_po_number))
            current_po = self._parse_sequence_number("PO", current_po_number)
            if prev_po is not None and current_po is not None and current_po <= prev_po:
                raise ValueError("Purchase order number must advance beyond the previous PO.")
            if current_po == prev_po:
                raise ValueError("Duplicate purchase order number detected.")

        if previous_quote_id:
            prev_quote = self._parse_sequence_number("QTE", str(previous_quote_id))
            current_quote = self._parse_sequence_number("QTE", current_quote_id)
            if prev_quote is not None and current_quote is not None and current_quote <= prev_quote:
                raise ValueError("Quote number must advance beyond the previous quote.")
            if current_quote == prev_quote:
                raise ValueError("Duplicate quote number detected.")

        if previous_po_number and previous_quote_id:
            if current_po_number == str(previous_po_number).strip() or current_quote_id == str(previous_quote_id).strip():
                raise ValueError("Purchase order or quote metadata is duplicated.")

    def _sending_enabled(self) -> bool:
        return os.getenv("EMAIL_SEND_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def request_part_quotes(
        self,
        part_number: str,
        quantity: int,
        reply_to: Optional[str] = None,
        condition_requested: str = "NE",
        certification_requested: str = "FAA 8130-3",
    ) -> List[Dict[str, Any]]:
        recipients = [supplier.get("email") for supplier in supplier_db.list_suppliers() if supplier.get("email")]
        configured = os.getenv("SUPPLIER_REQUEST_RECIPIENTS", "")
        recipients.extend(address.strip() for address in configured.split(",") if address.strip())
        recipients = list(dict.fromkeys(recipients))
        results = []
        for recipient in recipients:
            supplier_contact = next(
                (row.get("company_name") for row in supplier_db.list_suppliers() if row.get("email") == recipient),
                "Supplier Team",
            )
            template = compose_supplier_rfq(SupplierRFQData(
                supplier_contact=supplier_contact,
                recipient_email=recipient,
                part_number=part_number.upper(),
                quantity=quantity,
                condition_requested=condition_requested,
                certification_requested=certification_requested,
            ))
            prepare_and_validate_email(
                rfq_id=f"RFQ-{part_number.upper()}",
                recipient_email=recipient,
                subject=template.subject,
                part_rows=[{"part_number": part_number, "description": part_number, "quantity": quantity, "unit_price": None}],
            )
            results.append(self._send("purchasing", recipient, template.subject, template.body, reply_to=reply_to))
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
        previous_po_number: Optional[str] = None,
        previous_quote_id: Optional[str] = None,
        review_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.validate_purchase_order_metadata(
            po_number=po_number,
            customer_email=customer_email,
            quote_id=quote_id,
            previous_po_number=previous_po_number,
            previous_quote_id=previous_quote_id,
        )
        safe_customer_name = safe_display_text(customer_name)
        total_value = sum(float(item.get("unit_price") or 0) * int(item.get("quantity") or 0) for item in items)
        item_lines = []
        for item in items:
            item_lines.append(
                f"- {item['part_number']} | Qty {item['quantity']} | Customer price ${item['unit_price']:,.2f} | "
                f"Selected supplier: {item.get('supplier_name', 'Internal inventory')} | "
                f"Supplier cost: ${item.get('supplier_unit_cost', 0.0):,.2f}"
            )
        body = (
            f"Purchase order received: {po_number}\n\n"
            f"Customer: {safe_customer_name}\nCustomer email: {customer_email}\nQuote: {quote_id}\n"
            f"Total value: ${total_value:,.2f}\n\n"
            "Requested items:\n" + "\n".join(item_lines) + "\n\n"
            f"Review and approve this PO in the Sales Command Dashboard: {review_url or os.getenv('SALES_DASHBOARD_URL') or os.getenv('PUBLIC_APP_URL', 'http://localhost:3000')}\n\n"
            "Do not fulfill, invoice, or contact suppliers until a human operator approves this PO. "
            "Supplier details are included for internal use only."
        )
        return self._send(
            "sales",
            recipient,
            f"[ACTION REQUIRED] New Purchase Order Received - PO #{po_number}",
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
        if items:
            templates = [compose_supplier_verification(SupplierVerificationData(
                supplier_contact=supplier_name,
                recipient_email=recipient,
                part_number=item["part_number"],
                quantity=item["quantity"],
                po_number=po_number,
            )) for item in items]
            return self._send(
                "purchasing",
                recipient,
                templates[0].subject,
                "\n\n".join(template.body for template in templates),
                reply_to=reply_to,
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
        quote_items: Optional[List[Dict[str, Any]]] = None,
        subject_override: Optional[str] = None,
        body_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = subject_override or f"Winged Tycoons quotation {quote_id}"
        quote_body = str(quote_summary or "").strip()
        if not quote_body:
            quote_body = "Please see the approved quotation below."

        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")

        if not str(quote_summary or "").strip():
            raise ValueError("Quote summary is required before dispatching a customer email.")

        quote_details = db_service.get_quote(quote_id)
        structured_quote_items = quote_items or []
        quote_items = db_service.get_quote_items(quote_id) if quote_details else structured_quote_items
        rfq = db_service.get_rfq(quote_details.rfq_id) if quote_details else None
        if rfq and recipient.lower() != rfq.customer_email.lower():
            raise ValueError("Customer recipient does not match the persisted RFQ recipient. Email aborted.")
        if quote_details:
            validated_payload = prepare_and_validate_email(
                rfq_id=quote_details.rfq_id,
                recipient_email=recipient,
                subject=subject,
                part_rows=[
                    {
                        "part_number": item.part_number,
                        "description": item.part_number,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                    }
                    for item in quote_items
                ],
            )
            if not validated_payload:
                raise ValueError("Quote payload is missing required SQL-backed item data. Email not sent.")
        elif quote_items:
            prepare_and_validate_email(
                rfq_id=quote_id,
                recipient_email=recipient,
                subject=subject,
                part_rows=quote_items,
            )
        elif self._sending_enabled():
            raise ValueError("Persisted or structured quote item data is required before live customer dispatch.")

        first_item = quote_items[0] if quote_items else None
        rfq_items = db_service.get_rfq_items(quote_details.rfq_id) if quote_details else []
        rfq_item = rfq_items[0] if rfq_items else None
        if quote_details and first_item:
            template = compose_customer_quote(CustomerQuoteData(
                contact_name=safe_display_text(customer_name),
                recipient_email=recipient,
                quote_number=quote_id,
                part_number=first_item.part_number,
                description=first_item.description or first_item.part_number,
                quantity=first_item.quantity,
                condition=(first_item.condition or getattr(rfq_item, "condition_preference", None) or "Available"),
                certification=first_item.certificate_type or "Available upon request",
                unit_price=first_item.unit_price,
                lead_time=(f"{quote_details.lead_time_days} days" if quote_details.lead_time_days is not None else "Available upon request"),
                valid_until=quote_details.valid_until or "Available upon request",
            ))
            if not subject_override:
                subject = template.subject
            body = template.body
        else:
            body = (
                f"Dear {safe_display_text(customer_name)},\n\n"
                "Thank you for your request. Please find the approved quotation below.\n\n"
                f"{quote_body}\n\n"
                "Shipping is customer-selected and not included in the proposal. Please reply with your purchase order or any questions. "
                "We will keep this conversation together for follow-up.\n\n"
                "Best regards,\nWinged Tycoons Sales Team"
            )
        if body_override:
            body = body_override.strip()
            if not body:
                raise ValueError("Generated customer email body is empty. Email dispatch aborted.")
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
        customer_timezone: str = "UTC",
    ) -> Dict[str, Any]:
        delay_minutes = int(os.getenv("CUSTOMER_FOLLOWUP_DELAY_MINUTES", "30"))
        try:
            local_zone = timezone.utc if customer_timezone.upper() == "UTC" else ZoneInfo(customer_timezone)
        except Exception as exc:
            raise ValueError(f"Unknown customer timezone: {customer_timezone}") from exc
        local_now = datetime.now(timezone.utc).astimezone(local_zone)
        due = local_now + timedelta(minutes=delay_minutes)
        if due.weekday() >= 5 or due.hour < 8 or due.hour >= 18:
            due += timedelta(days=(7 - due.weekday()) if due.weekday() >= 5 else 1)
            due = due.replace(hour=9, minute=0, second=0, microsecond=0)
        due_at = due.astimezone(timezone.utc).isoformat()
        quote = db_service.get_quote(quote_id)
        quote_items = db_service.get_quote_items(quote_id) if quote else []
        part_number = quote_items[0].part_number if quote_items else "the quoted part"
        template = compose_customer_followup(CustomerFollowupData(
            contact_name=safe_display_text(customer_name),
            recipient_email=recipient,
            part_number=part_number,
            quote_number=quote_id,
        ))
        return supplier_db.schedule_communication_task(
            task_key=f"customer-followup:{quote_id}",
            task_type="customer_followup",
            mailbox="sales",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
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
        quantity: int = 1,
    ) -> Dict[str, Any]:
        max_rounds = int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "2"))
        if round_number > max_rounds:
            return {"status": "LIMIT_REACHED", "round": round_number}
        template = compose_supplier_discount_request(SupplierDiscountData(
            supplier_contact=safe_display_text(supplier_name),
            recipient_email=recipient,
            part_number=part_number.upper(),
            quantity=quantity,
            quoted_price=unit_cost,
        ))
        return supplier_db.schedule_communication_task(
            task_key=f"supplier-discount:{source_email_id}:{round_number}",
            task_type="supplier_discount_request",
            mailbox="purchasing",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
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
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        if self._sending_enabled():
            send_message(mailbox, recipient, subject, body, reply_to=reply_to)
            result["transmission_status"] = "SENT"
        communication_id = operations_store.record_communication(
            entity_type="email",
            entity_id=reply_to or subject,
            recipient=recipient,
            sender=MAILBOXES[mailbox].address,
            channel="email",
            subject=subject,
            message=body,
            message_type="outbound",
            status=result["transmission_status"],
        )
        operations_store.record_automation_event(
            event_type="email_dispatch",
            entity_type="email",
            entity_id=communication_id,
            status=result["transmission_status"],
            result=json.dumps({"mailbox": mailbox, "recipient": recipient}),
        )
        result["communication_id"] = communication_id
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
            "Please also confirm whether the quoted material is in stock, whether there is any standard volume or "
            "bulk-buy adjustment available, and whether the proposed price is subject to any certification or "
            "documentation add-ons. Shipping is not included in our customer quotations and is customer-selected. "
            "Thank you.\n\n"
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
