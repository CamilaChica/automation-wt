"""Natural-language supplier and customer email workflows."""

import asyncio
import os
import re
import json
import hashlib
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from services.db_service import db_service
from services.customer_question_service import CustomerQuestionService
from services.customer_chase_schedule import chase_days, chase_task_keys
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

customer_question_service = CustomerQuestionService()


def _next_customer_business_window(due: datetime) -> datetime:
    while due.weekday() >= 5 or due.hour < 8 or due.hour >= 18:
        if due.weekday() >= 5:
            due += timedelta(days=7 - due.weekday())
            due = due.replace(hour=9, minute=0, second=0, microsecond=0)
        elif due.hour < 8:
            due = due.replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            due = (due + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return due


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
    parts: List[PartItem] = Field(..., min_length=1)

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
        suppliers = (
            operations_store.list_suppliers()
            if operations_store.storage_engine == "postgresql"
            else supplier_db.list_suppliers()
        )
        recipients = [supplier.get("email") for supplier in suppliers if supplier.get("email")]
        configured = os.getenv("SUPPLIER_REQUEST_RECIPIENTS", "")
        recipients.extend(address.strip() for address in configured.split(",") if address.strip())
        recipients = [
            address for address in dict.fromkeys(recipients)
            if address and "@" in address
            and address.split("@", 1)[0].lower() not in {"mailer-daemon", "postmaster", "noreply", "no-reply"}
            and not address.lower().endswith("@wingedtycoons.com")
            and not address.lower().endswith("@onmicrosoft.com")
        ]
        results = []
        for recipient in recipients:
            supplier_contact = next(
                (row.get("company_name") for row in suppliers if row.get("email") == recipient),
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
        return self._send(
            "purchasing", recipient, subject, body, reply_to=reply_to,
            deduplication_key=self._supplier_info_key(recipient, part_number),
        )

    @staticmethod
    def _supplier_info_key(recipient: str, part_number: str) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"supplier-info:{recipient.strip().lower()}:{part_number.strip().upper()}:{day}"

    async def request_missing_supplier_fields_async(
        self,
        repositories,
        recipient: str,
        part_number: str,
        missing_fields: List[str],
        reply_to: Optional[str] = None,
        *,
        entity_id: str | None = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        subject = f"Re: RFQ request: {part_number.upper()} - information needed"
        body = self._missing_fields_request(part_number, missing_fields)
        key = self._supplier_info_key(recipient, part_number)
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=key,
            mailbox="purchasing",
            recipient=recipient,
            subject=subject,
            body=body,
            reply_to=reply_to,
            entity_id=entity_id,
        )
        return {
            "mailbox": "purchasing",
            "recipient": recipient,
            "subject": subject,
            "reply_to": reply_to,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

    def request_stale_supplier_confirmation(
        self,
        recipient: str,
        supplier_name: str,
        part_number: str,
        quantity: int,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = f"Re: Quote confirmation request - {part_number.upper()}"
        body = (
            f"Hello {supplier_name},\n\n"
            f"We are reviewing your previous quotation for part {part_number.upper()} (quantity {quantity}). "
            "Please confirm in this same email thread whether the quoted material is still available and whether "
            "the price, condition, certification, lead time, and quote validity remain current.\n\n"
            "If any detail has changed, please provide the updated value and attach the applicable trace documentation.\n\n"
            "Best regards,\nWinged Tycoons Purchasing Team"
        )
        return self._send("purchasing", recipient, subject, body, reply_to=reply_to)

    def request_supplier_body_quote(
        self,
        recipient: str,
        part_reference: str = "the quoted part",
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = f"Re: Quote details required - {part_reference}"
        body = (
            "Hello,\n\n"
            "We could not read the quotation attachment in your email. Please reply in this same email thread "
            "with the quotation details in the message body so we can process your response:\n"
            "- Part number\n"
            "- Quantity available\n"
            "- Unit price and currency\n"
            "- Condition\n"
            "- Release certificate and trace documentation\n"
            "- Lead time\n"
            "- Quote validity or expiration date\n\n"
            "Please do not send a new thread; replying here preserves the quote reference.\n\n"
            "Best regards,\nWinged Tycoons Purchasing Team"
        )
        return self._send("purchasing", recipient, subject, body, reply_to=reply_to)

    async def request_supplier_body_quote_async(
        self,
        repositories,
        recipient: str,
        part_reference: str = "the quoted part",
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        subject = f"Re: Quote details required - {part_reference}"
        body = (
            "Hello,\n\n"
            "We could not read the quotation attachment in your email. Please reply in this same email thread "
            "with the quotation details in the message body so we can process your response:\n"
            "- Part number\n"
            "- Quantity available\n"
            "- Unit price and currency\n"
            "- Condition\n"
            "- Release certificate and trace documentation\n"
            "- Lead time\n"
            "- Quote validity or expiration date\n\n"
            "Please do not send a new thread; replying here preserves the quote reference.\n\n"
            "Best regards,\nWinged Tycoons Purchasing Team"
        )
        deduplication_key = hashlib.sha256(
            "\0".join(("purchasing", recipient.lower(), subject, body, reply_to or "")).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="purchasing",
            recipient=recipient,
            subject=subject,
            body=body,
            reply_to=reply_to,
        )
        return {
            "mailbox": "purchasing",
            "recipient": recipient,
            "subject": subject,
            "reply_to": reply_to,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

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
        subject, body = self._purchase_order_notification_content(
            po_number, customer_name, customer_email, quote_id, items,
            previous_po_number, previous_quote_id, review_url,
        )
        return self._send("sales", recipient, subject, body, reply_to=None)

    def _purchase_order_notification_content(
        self,
        po_number: str,
        customer_name: str,
        customer_email: str,
        quote_id: str,
        items: List[Dict[str, Any]],
        previous_po_number: Optional[str] = None,
        previous_quote_id: Optional[str] = None,
        review_url: Optional[str] = None,
    ) -> tuple[str, str]:
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
        return (
            f"[ACTION REQUIRED] New Purchase Order Received - PO #{po_number}",
            body,
        )

    async def notify_purchase_order_async(
        self,
        repositories,
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
        subject, body = self._purchase_order_notification_content(
            po_number, customer_name, customer_email, quote_id, items,
            previous_po_number, previous_quote_id, review_url,
        )
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        deduplication_key = hashlib.sha256(
            "\0".join(("sales", recipient.lower(), subject, body, "", "", quote_id)).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            entity_id=quote_id,
        )
        return {
            "mailbox": "sales",
            "recipient": recipient,
            "subject": subject,
            "reply_to": None,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

    def send_shipment_tracking_link(self, recipient: str, shipment_id: str, public_token: str) -> Dict[str, Any]:
        subject, body = self._shipment_tracking_content(shipment_id, public_token)
        return self._send("sales", recipient, subject, body, reply_to=None)

    def _shipment_tracking_content(self, shipment_id: str, public_token: str) -> tuple[str, str]:
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
        return f"Shipment tracking available - {shipment_id}", body

    async def send_shipment_tracking_link_async(
        self, repositories, recipient: str, shipment_id: str, public_token: str
    ) -> Dict[str, Any]:
        subject, body = self._shipment_tracking_content(shipment_id, public_token)
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        deduplication_key = hashlib.sha256(
            "\0".join(("sales", recipient.lower(), subject, body, "", "", shipment_id)).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            entity_id=shipment_id,
        )
        return {
            "mailbox": "sales",
            "recipient": recipient,
            "subject": subject,
            "reply_to": None,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

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
        if operations_store.storage_engine == "postgresql" and quote_details:
            with operations_store.transaction():
                result = self._send(
                    "sales", recipient, subject, body, reply_to=reply_to,
                    entity_id=quote_id, deduplication_key=f"customer-quote:{quote_id}",
                )
                self.schedule_customer_followup(
                    recipient=recipient,
                    customer_name=customer_name,
                    quote_id=quote_id,
                    reply_to=reply_to,
                )
        else:
            result = self._send(
                "sales", recipient, subject, body, reply_to=reply_to,
                entity_id=quote_id, deduplication_key=f"customer-quote:{quote_id}",
            )
            self.schedule_customer_followup(
                recipient=recipient,
                customer_name=customer_name,
                quote_id=quote_id,
                reply_to=reply_to,
            )
        return result

    async def enqueue_customer_quote_async(
        self,
        repositories,
        *,
        recipient: str,
        quote_id: str,
        rfq_id: str,
        subject: str,
        body: str,
        quote_items: List[Dict[str, Any]],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        if not str(body or "").strip():
            raise ValueError("Customer email body is empty. Email dispatch aborted.")
        prepare_and_validate_email(
            rfq_id=rfq_id,
            recipient_email=recipient,
            subject=subject,
            part_rows=quote_items,
        )
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=f"customer-quote:{quote_id}",
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body.strip(),
            reply_to=reply_to,
            entity_id=quote_id,
        )
        return {
            "mailbox": "sales",
            "recipient": recipient,
            "subject": subject,
            "reply_to": reply_to,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

    async def schedule_customer_followups_async(
        self,
        repositories,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        part_number: str,
        reply_to: Optional[str] = None,
        customer_timezone: str = "UTC",
    ) -> list[Dict[str, Any]]:
        try:
            local_zone = timezone.utc if customer_timezone.upper() == "UTC" else ZoneInfo(customer_timezone)
        except Exception as exc:
            raise ValueError(f"Unknown customer timezone: {customer_timezone}") from exc
        local_now = datetime.now(timezone.utc).astimezone(local_zone)
        template = compose_customer_followup(CustomerFollowupData(
            contact_name=safe_display_text(customer_name),
            recipient_email=recipient,
            part_number=part_number,
            quote_number=quote_id,
        ))
        scheduled = []
        for index, days in enumerate(chase_days(), start=1):
            due = _next_customer_business_window(local_now + timedelta(days=days))
            scheduled.append(await repositories.records.schedule_communication_task(
                task_key=chase_task_keys(quote_id)[index - 1],
                task_type="customer_followup",
                mailbox="sales",
                recipient=recipient,
                subject=template.subject,
                body=template.body,
                due_at=due.astimezone(timezone.utc),
                reply_to=reply_to,
            ))
        return scheduled

    def send_rfq_acknowledgement(
        self,
        *,
        rfq_id: str,
        recipient: str,
        customer_name: str | None,
        part_numbers: List[str],
        reply_to: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        certifications: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Tell the customer, in-thread and once per RFQ, what we understood and what to confirm."""
        if not recipient or not self._is_valid_email(recipient):
            return None
        lowered = recipient.lower()
        if "partsbase" in lowered or lowered.endswith("@wingedtycoons.com"):
            return None
        name = safe_display_text(customer_name or "") or "there"
        lines: List[str] = []
        to_confirm: List[str] = []
        seen: set[str] = set()
        for item in items or [{"requested_part_number": p} for p in part_numbers]:
            pn = safe_display_text(str(item.get("requested_part_number") or ""), fallback="").strip()
            if not pn or pn in seen:
                continue
            seen.add(pn)
            qty = item.get("quantity") or 1
            qty_text = f"{qty}" + (" (assumed)" if item.get("quantity_defaulted") or not item.get("quantity") else "")
            condition = safe_display_text(str(item.get("condition_preference") or ""), fallback="").strip()
            cond_text = condition or "any available (NE / NS / OH / SV)"
            lines.append(f"  - P/N {pn}: Qty {qty_text}, Condition {cond_text}")
            if "(assumed)" in qty_text:
                to_confirm.append(f"the quantity you need for {pn}")
            if not condition:
                to_confirm.append(f"your preferred condition for {pn}")
        if not lines:
            lines.append("  - the requested parts")
        if not certifications:
            to_confirm.append("any certification you require (e.g. FAA 8130-3, EASA Form 1)")
        confirm_text = ""
        if to_confirm:
            confirm_text = (
                "To make sure we quote exactly what you need, could you please confirm:\n"
                + "\n".join(f"  - {entry}" for entry in dict.fromkeys(to_confirm))
                + "\n\nWe are already working on your quote while you reply, so nothing is on hold.\n\n"
            )
        body = (
            f"Hello {name},\n\n"
            f"Thank you for your request for quote. We have received it under reference {rfq_id}, "
            "and this is what we understood:\n\n"
            + "\n".join(lines)
            + "\n\n"
            "Our team is checking our inventory and supplier network right now, and we will send you our "
            "quotation in this same email thread as soon as it is ready.\n\n"
            + confirm_text
            + "Just reply to this email with any changes or details.\n\n"
            "Best regards,\nWinged Tycoons Sales Team"
        )
        return self._send(
            "sales",
            recipient,
            f"Re: Your request for quote {rfq_id} - received",
            body,
            reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"rfq-ack:{rfq_id}",
        )

    def send_customer_information_response(
        self,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        request_text: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reply in-thread to a customer asking for quote supporting details."""
        quote = db_service.get_quote(quote_id)
        if not quote:
            raise ValueError(f"Quote {quote_id} was not found for customer response.")
        items = db_service.get_quote_items(quote_id)
        grounded_answer = customer_question_service.answer_from_quote(request_text, quote, items)
        if not grounded_answer:
            raise ValueError("The customer question could not be answered from approved quote data.")
        body = (
            f"Dear {safe_display_text(customer_name)},\n\n"
            f"Thank you for your question regarding quotation {quote_id}. The approved quote records:\n\n"
            f"{grounded_answer}\n\n"
            "Kind regards,\nWinged Tycoons Aviation Team"
        )
        return self._send(
            "sales",
            recipient,
            f"Re: Quotation {quote_id} - requested details",
            body,
            reply_to=reply_to,
        )

    async def send_customer_information_response_async(
        self,
        repositories,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        request_text: str,
        quote,
        items: list,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        grounded_answer = customer_question_service.answer_from_quote(request_text, quote, items)
        if not grounded_answer:
            raise ValueError("The customer question could not be answered from approved quote data.")
        body = (
            f"Dear {safe_display_text(customer_name)},\n\n"
            f"Thank you for your question regarding quotation {quote_id}. The approved quote records:\n\n"
            f"{grounded_answer}\n\n"
            "Kind regards,\nWinged Tycoons Aviation Team"
        )
        subject = f"Re: Quotation {quote_id} - requested details"
        deduplication_key = hashlib.sha256(
            "\0".join(("sales", recipient.lower(), subject, body, reply_to or "", "", quote_id)).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            reply_to=reply_to,
            entity_id=quote_id,
        )
        return {
            "mailbox": "sales",
            "recipient": recipient,
            "subject": subject,
            "reply_to": reply_to,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

    def schedule_customer_followup(
        self,
        recipient: str,
        customer_name: str,
        quote_id: str,
        reply_to: Optional[str] = None,
        customer_timezone: str = "UTC",
    ) -> Dict[str, Any]:
        try:
            local_zone = timezone.utc if customer_timezone.upper() == "UTC" else ZoneInfo(customer_timezone)
        except Exception as exc:
            raise ValueError(f"Unknown customer timezone: {customer_timezone}") from exc
        local_now = datetime.now(timezone.utc).astimezone(local_zone)
        quote = db_service.get_quote(quote_id)
        quote_items = db_service.get_quote_items(quote_id) if quote else []
        part_number = quote_items[0].part_number if quote_items else "the quoted part"
        template = compose_customer_followup(CustomerFollowupData(
            contact_name=safe_display_text(customer_name),
            recipient_email=recipient,
            part_number=part_number,
            quote_number=quote_id,
        ))
        scheduled = []
        for index, days in enumerate(chase_days(), start=1):
            due = _next_customer_business_window(local_now + timedelta(days=days))
            scheduled.append(self._schedule_communication_task(
                task_key=chase_task_keys(quote_id)[index - 1],
                task_type="customer_followup",
                mailbox="sales",
                recipient=recipient,
                subject=template.subject,
                body=template.body,
                due_at=due.astimezone(timezone.utc).isoformat(),
                reply_to=reply_to,
            ))
        return scheduled[0]

    def cancel_customer_followups(self, quote_id: str) -> None:
        for task_key in chase_task_keys(quote_id):
            if operations_store.storage_engine == "postgresql":
                operations_store.cancel_communication_task(task_key)
            else:
                supplier_db.cancel_communication_task(task_key)
        if operations_store.storage_engine == "postgresql":
            operations_store.cancel_communication_task(f"customer-followup:{quote_id}")
        else:
            supplier_db.cancel_communication_task(f"customer-followup:{quote_id}")

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
        return self._schedule_communication_task(
            task_key=f"supplier-discount:{source_email_id}:{round_number}",
            task_type="supplier_discount_request",
            mailbox="purchasing",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
            due_at=datetime.now(timezone.utc).isoformat(),
            reply_to=reply_to,
        )

    async def schedule_supplier_discount_request_async(
        self,
        repositories,
        *,
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
        return await repositories.records.schedule_communication_task(
            task_key=f"supplier-discount:{source_email_id}:{round_number}",
            task_type="supplier_discount_request",
            mailbox="purchasing",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
            due_at=datetime.now(timezone.utc),
            reply_to=reply_to,
        )

    @staticmethod
    def _schedule_communication_task(**task: Any) -> Dict[str, Any]:
        if operations_store.storage_engine != "postgresql":
            return supplier_db.schedule_communication_task(**task)
        due_at = task["due_at"]
        due = datetime.fromisoformat(due_at) if isinstance(due_at, str) else due_at
        return operations_store.schedule_communication_task(
            **{**task, "due_at": due}
        )

    def process_due_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        result = self._send(
            task["mailbox"],
            task["recipient"],
            task["subject"],
            task["body"],
            reply_to=task.get("reply_to"),
            communication_task_id=task.get("id"),
        )
        return result

    async def process_due_task_async(self, repositories, task: Dict[str, Any]) -> Dict[str, Any]:
        mailbox = str(task.get("mailbox") or "sales")
        recipient = str(task.get("recipient") or "")
        if mailbox not in MAILBOXES:
            raise ValueError("Unknown outbound mailbox.")
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        task_id = str(task["id"])
        deduplication_key = hashlib.sha256(
            "\0".join((mailbox, recipient.lower(), str(task.get("subject") or ""),
                       str(task.get("body") or ""), str(task.get("reply_to") or ""), task_id, "")).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox=mailbox,
            recipient=recipient,
            subject=str(task.get("subject") or ""),
            body=str(task.get("body") or ""),
            reply_to=task.get("reply_to"),
            communication_task_id=task_id,
        )
        return {
            "mailbox": mailbox,
            "recipient": recipient,
            "subject": task.get("subject"),
            "reply_to": task.get("reply_to"),
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
        }

    def send_manual_message(self, *, mailbox: str, recipient: str, subject: str, body: str, reply_to: str | None = None) -> Dict[str, Any]:
        if mailbox not in MAILBOXES:
            raise ValueError("Unknown outbound mailbox.")
        return self._send(
            mailbox, recipient, subject, body, reply_to=reply_to,
            entity_id=f"manual:{mailbox}",
        )

    def _send(
        self,
        mailbox: str,
        recipient: str,
        subject: str,
        body: str,
        reply_to: Optional[str],
        communication_task_id: str | None = None,
        entity_id: str | None = None,
        deduplication_key: str | None = None,
    ) -> Dict[str, Any]:
        if operations_store.storage_engine == "postgresql":
            dedupe_material = "\0".join((mailbox, recipient.lower(), subject, body, reply_to or "", communication_task_id or "", entity_id or ""))
            deduplication_key = deduplication_key or hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()
            if not self._is_valid_email(recipient):
                raise ValueError("Recipient email is invalid. Email dispatch aborted.")
            queued = operations_store.enqueue_outbox_message(
                deduplication_key=deduplication_key,
                mailbox=mailbox,
                recipient=recipient,
                subject=subject,
                body=body,
                reply_to=reply_to,
                communication_task_id=communication_task_id,
                entity_id=entity_id,
            )
            return {
                "mailbox": mailbox,
                "recipient": recipient,
                "subject": subject,
                "reply_to": reply_to,
                "transmission_status": queued["status"],
                "communication_id": queued["id"],
                "outbox_id": queued["id"],
            }
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

    def dispatch_outbox_once(self, *, limit: int = 25) -> dict[str, int]:
        if operations_store.storage_engine != "postgresql":
            return {"sent": 0, "failed": 0}
        operations_store.recover_stale_outbox_messages()
        sent = 0
        failed = 0
        for message in operations_store.claim_outbox_messages(limit=limit):
            payload = message.get("payload") or {}
            body = payload.get("body", "") if isinstance(payload, dict) else str(payload)
            try:
                send_message(
                    message["mailbox"],
                    message["recipient"],
                    message["subject"],
                    body,
                    reply_to=message.get("reply_to"),
                )
            except Exception as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None) or getattr(exc, "status_code", None) or getattr(exc, "smtp_code", None)
                try:
                    status_code = int(status_code) if status_code is not None else None
                except (TypeError, ValueError):
                    status_code = None
                retryable = status_code == 429 or bool(status_code and 500 <= status_code < 600)
                delivery_state = operations_store.fail_outbox_message(
                    message["id"], f"{type(exc).__name__}: {exc}", retryable=retryable
                )
                if delivery_state == "MANUAL_REVIEW_REQUIRED" and message.get("entity_id"):
                    quote = db_service.get_quote(str(message["entity_id"]))
                    if quote and quote.status in {"Draft", "Approved", "Pending_Dispatch", "Dispatch_Pending"}:
                        db_service.update_quote_status(quote.id, "Pending_Internal_Review")
                        operations_store.update_customer_quote_status(quote.id, "Pending_Internal_Review")
                        rfq = db_service.get_rfq(quote.rfq_id)
                        if rfq and rfq.status in {
                            "Quote_Generation", "Pending_Approval", "Pending_Approval_Low_Margin",
                            "Quote_Dispatch_Pending",
                        }:
                            db_service.update_rfq_status(rfq.id, "Pending_Internal_Review")
                        self.cancel_customer_followups(quote.id)
                failed += 1
                continue

            try:
                with operations_store.transaction():
                    operations_store.record_communication(
                        entity_type="email",
                        entity_id=message["id"],
                        recipient=message["recipient"],
                        sender=MAILBOXES[message["mailbox"]].address,
                        channel="email",
                        subject=message["subject"],
                        message=body,
                        message_type="outbound",
                        status="SENT",
                    )
                    operations_store.mark_outbox_sent(message["id"])
                    if message.get("entity_id"):
                        quote = db_service.get_quote(str(message["entity_id"]))
                        if quote and quote.status in {"Draft", "Approved", "Pending_Dispatch", "Dispatch_Pending"}:
                            db_service.update_quote_status(quote.id, "Sent")
                            operations_store.update_customer_quote_status(quote.id, "Sent")
                            rfq = db_service.get_rfq(quote.rfq_id)
                            if rfq and rfq.status in {
                                "Quote_Generation", "Pending_Approval", "Pending_Approval_Low_Margin",
                                "Quote_Dispatch_Pending",
                            }:
                                db_service.update_rfq_status(rfq.id, "Quote_Sent")
                sent += 1
            except Exception as exc:
                operations_store.fail_outbox_message(
                    message["id"],
                    f"Delivery accepted but database finalization failed: {type(exc).__name__}: {exc}",
                    retryable=False,
                )
                failed += 1
        return {"sent": sent, "failed": failed}

    async def dispatch_outbox_once_async(self, engine, *, limit: int = 25) -> dict[str, int]:
        from repositories.runtime import create_operational_repositories
        from services.async_database import session_scope

        async with session_scope(engine) as session:
            repositories = create_operational_repositories(session)
            await repositories.records.recover_stale_outbox_messages()
            claimed = await repositories.records.claim_outbox_messages(limit=limit)

        sent = 0
        failed = 0
        for message in claimed:
            payload = message.get("payload") or {}
            body = payload.get("body", "") if isinstance(payload, dict) else str(payload)
            error = None
            retryable = False
            try:
                await asyncio.to_thread(
                    send_message,
                    message["mailbox"],
                    message["recipient"],
                    message["subject"],
                    body,
                    reply_to=message.get("reply_to"),
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None) or getattr(exc, "status_code", None) or getattr(exc, "smtp_code", None)
                try:
                    status_code = int(status_code) if status_code is not None else None
                except (TypeError, ValueError):
                    status_code = None
                retryable = status_code == 429 or bool(status_code and 500 <= status_code < 600)

            try:
                async with session_scope(engine) as session:
                    repositories = create_operational_repositories(session)
                    if error is not None:
                        delivery_state = await repositories.records.fail_outbox_message(
                            message["id"], error, retryable=retryable
                        )
                        if delivery_state == "MANUAL_REVIEW_REQUIRED" and message.get("entity_id"):
                            await repositories.quote.finalize_outbox_delivery(
                                str(message["entity_id"]), delivered=False, error=error
                            )
                        failed += 1
                        continue

                    await repositories.records.record_communication(
                        entity_type="email",
                        entity_id=message["id"],
                        recipient=message["recipient"],
                        sender=MAILBOXES[message["mailbox"]].address,
                        channel="email",
                        subject=message["subject"],
                        message=body,
                        message_type="outbound",
                        status="SENT",
                    )
                    await repositories.records.mark_outbox_sent(message["id"])
                    if message.get("entity_id"):
                        await repositories.quote.finalize_outbox_delivery(
                            str(message["entity_id"]), delivered=True
                        )
                    sent += 1
            except Exception as exc:
                try:
                    async with session_scope(engine) as session:
                        repositories = create_operational_repositories(session)
                        error = f"Delivery accepted but database finalization failed: {type(exc).__name__}: {exc}"
                        delivery_state = await repositories.records.fail_outbox_message(
                            message["id"], error, retryable=False
                        )
                        if delivery_state == "MANUAL_REVIEW_REQUIRED" and message.get("entity_id"):
                            await repositories.quote.finalize_outbox_delivery(
                                str(message["entity_id"]), delivered=False, error=error
                            )
                except Exception:
                    logger.exception("Failed to quarantine outbox message after finalization error id=%s", message["id"])
                failed += 1
        return {"sent": sent, "failed": failed}

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
