"""Natural-language supplier and customer email workflows."""

import asyncio
import base64
import email
import html as html_lib
import logging
import math
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
from services.customer_chase_schedule import chase_task_keys, final_chase_day
from services.email_context import safe_display_text
from services.email_templates import (
    CustomerFollowupData,
    CustomerQuoteData,
    SupplierDiscountData,
    SupplierRFQData,
    SupplierVerificationData,
    customer_followup as compose_customer_followup,
    customer_quote as compose_customer_quote,
    enforce_customer_email_policy,
    customer_portal_url,
    supplier_discount_request as compose_supplier_discount_request,
    supplier_rfq as compose_supplier_rfq,
    supplier_verification as compose_supplier_verification,
)
from services.mailbox_service import MAILBOXES, ensure_staging_recipient_allowed, send_message
from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.email_program_runtime import email_program_runtime
from services.document_verification import compare_documents

logger = logging.getLogger(__name__)

customer_question_service = CustomerQuestionService()


def _serialize_email_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    serialized = []
    total_bytes = 0
    for attachment in attachments or []:
        content = attachment.get("content")
        if not isinstance(content, bytes):
            raise ValueError("Email attachment content must be bytes.")
        total_bytes += len(content)
        if total_bytes > 25 * 1024 * 1024:
            raise ValueError("Email attachments exceed the 25 MB combined limit.")
        serialized.append({
            "filename": str(attachment.get("filename") or "attachment"),
            "content_type": str(attachment.get("content_type") or "application/octet-stream"),
            "content_base64": base64.b64encode(content).decode("ascii"),
        })
    return serialized


def _deserialize_email_attachments(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    decoded = []
    for attachment in attachments or []:
        try:
            content = base64.b64decode(attachment["content_base64"], validate=True)
        except (KeyError, ValueError) as exc:
            raise ValueError("Queued email attachment is invalid or corrupted.") from exc
        decoded.append({
            "filename": attachment.get("filename") or "attachment",
            "content_type": attachment.get("content_type") or "application/octet-stream",
            "content": content,
        })
    return decoded


def _customer_inquiry_body(customer_name: str, tone: str, quote_id: str, quote: Any, answer: str) -> str:
    status = quote.get("status") if isinstance(quote, dict) else getattr(quote, "status", None)
    status_text = str(status or "In Progress").replace("_", " ").title()
    return (
        f"Hi {safe_display_text(customer_name)},\n\n"
        f"Thanks for reaching out! {tone}\n"
        "Here is the latest update regarding your inquiry:\n\n"
        "**Quick Summary**\n"
        f"- **Status:** {status_text}\n"
        f"- **Reference:** `{quote_id}`\n\n"
        "---\n\n"
        "**Details & Answers**\n"
        f"{answer}\n\n"
        "---\n\n"
        "**Next Steps:** To move forward, simply reply to this email with your PO, "
        "or place it through our customer portal.\n\n"
        "Please let me know if you need any additional details in the meantime!\n\n"
        "Warm regards,\nCamila Chica\nWinged Tycoons Team"
    )


def _customer_html_from_text(body: str) -> str:
    rendered = []
    for line in html_lib.escape(body).split("\n"):
        if line.strip() == "---":
            rendered.append('<hr style="border:none;border-top:1px solid #d5dbe5;margin:14px 0">')
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(
            r"`([^`]+)`",
            r'<code style="font-family:Consolas,monospace;background:#eef2f7;padding:1px 4px;border-radius:3px">\1</code>',
            line,
        )
        rendered.append(line + "<br>")
    return (
        "<div style=\"font-family:Montserrat,Arial,sans-serif;color:#172033;line-height:1.6;max-width:760px\">"
        + "\n".join(rendered)
        + "</div>"
    )


def _source_documents_for_customer_request(question: str, items: list[Any]) -> list[dict[str, Any]]:
    if not customer_question_service.is_document_request(question):
        return []
    from services.mailbox_service import _extract_attachments_from_message

    allowed_extensions = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    def item_value(item, key):
        return item.get(key) if isinstance(item, dict) else getattr(item, key, None)

    specifically_requested = [
        item for item in items
        if str(item_value(item, "part_number") or "").strip()
        and re.search(
            r"(?<![A-Z0-9._/-])" + re.escape(str(item_value(item, "part_number")).strip())
            + r"(?![A-Z0-9._/-])", question, re.I,
        )
    ]
    for item in specifically_requested or items:
        source_message_id = item.get("source_email_id") if isinstance(item, dict) else getattr(item, "source_email_id", None)
        if not source_message_id:
            raise ValueError("requested_document_unavailable_from_verified_supplier_source")
        raw_mime = operations_store.get_raw_email_mime(str(source_message_id), mailbox="purchasing")
        if not raw_mime:
            raise ValueError("requested_document_unavailable_from_verified_supplier_source")
        message = email.message_from_bytes(raw_mime)
        candidates = []
        for attachment in _extract_attachments_from_message(message):
            filename = str(attachment.get("filename") or "")
            content = attachment.get("content")
            normalized_name = os.path.basename(filename).casefold()
            if (
                not content
                or os.path.splitext(normalized_name)[1] not in allowed_extensions
            ):
                continue
            candidates.append(attachment)
        expected_part = str(item_value(item, "part_number") or "").strip()
        if not expected_part:
            raise ValueError("requested_document_unavailable_from_verified_supplier_source")
        comparison = compare_documents(
            candidates, expected_part_number=expected_part,
            expected_serial_number=item_value(item, "serial_number"),
        )
        item_selected = False
        for attachment, document in zip(candidates, comparison["documents"]):
            if (
                document["read_status"] != "READABLE"
                or document["facts"].get("part_number") != expected_part.upper()
                or document["ambiguous_fields"]
                or document["document_type"] == "UNKNOWN"
                or any(discrepancy.startswith(document["filename"] + ":") for discrepancy in comparison["discrepancies"])
                or any(discrepancy.startswith(expected_part.upper() + ":") for discrepancy in comparison["discrepancies"])
                or re.search(
                    r"(?:unit\s*(?:price|cost)|total\s*(?:price|amount)|quotation|\$\s*\d)",
                    document["text"], re.I,
                )
            ):
                logger.warning("supplier_document_not_released filename=%s part=%s", document["filename"], expected_part)
                continue
            content = attachment["content"]
            item_selected = True
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                continue
            total_bytes += len(content)
            if total_bytes > 25 * 1024 * 1024:
                raise ValueError("Requested supplier documents exceed the 25 MB email attachment limit.")
            selected.append(attachment)
            seen.add(digest)
        if not item_selected:
            raise ValueError("requested_document_unavailable_from_verified_supplier_source")
    if not selected:
        raise ValueError("requested_document_unavailable_from_verified_supplier_source")
    return selected


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
        *,
        rfq_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        suppliers = (
            operations_store.list_suppliers()
            if operations_store.storage_engine == "postgresql"
            else supplier_db.list_suppliers()
        )
        configured = os.getenv("SUPPLIER_REQUEST_RECIPIENTS", "")
        recipients = [address.strip() for address in configured.split(",") if address.strip()]
        # Suppliers arrive ranked (approved, then quote history), so slicing keeps the most reliable wave.
        recipients.extend(supplier.get("email") for supplier in suppliers if supplier.get("email"))
        recipients = [
            address for address in dict.fromkeys(recipients)
            if address and "@" in address
            and address.split("@", 1)[0].lower() not in {"mailer-daemon", "postmaster", "noreply", "no-reply"}
            and not address.lower().endswith("@wingedtycoons.com")
            and not address.lower().endswith("@onmicrosoft.com")
        ]
        wave_size = max(1, int(os.getenv("SUPPLIER_RFQ_WAVE_SIZE", "40")))
        recipients = recipients[:wave_size]
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
                certification_requested=certification_requested or "Applicable airworthiness certification",
            ))
            prepare_and_validate_email(
                rfq_id=rfq_id or f"RFQ-{part_number.upper()}",
                recipient_email=recipient,
                subject=template.subject,
                part_rows=[{"part_number": part_number, "description": part_number, "quantity": quantity, "unit_price": None}],
            )
            fields = list(SUPPLIER_QUOTE_FIELDS)
            draft = email_program_runtime.draft_supplier_request(
                template.subject, template.body, part_number, fields,
            )
            outreach_key = hashlib.sha256(json.dumps({
                "rfq_id": rfq_id,
                "part_number": part_number.strip().upper(),
                "recipient": recipient.strip().lower(),
                "quantity": quantity,
                "condition": condition_requested,
                "certification": certification_requested,
            }, sort_keys=True).encode("utf-8")).hexdigest() if rfq_id else None
            result = self._send(
                "purchasing", recipient, draft["subject"], draft["body"], reply_to=reply_to,
                entity_id=rfq_id,
                deduplication_key=f"supplier-rfq:{outreach_key}" if outreach_key else None,
            )
            result["draft_generation"] = {
                key: value for key, value in draft.items() if key not in {"subject", "body"}
            }
            results.append(result)
        if not recipients:
            logger.warning("supplier_outreach_has_no_configured_recipients rfq=%s part=%s", rfq_id, part_number)
        return results

    def request_missing_supplier_fields(
        self,
        recipient: str,
        part_number: str,
        missing_fields: List[str],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        subject = f"Re: RFQ: Part # {part_number.upper()} | Missing Tag & Trace Info"
        body = self._missing_fields_request(part_number, missing_fields)
        draft = email_program_runtime.draft_supplier_request(subject, body, part_number, missing_fields)
        result = self._send(
            "purchasing", recipient, draft["subject"], draft["body"], reply_to=reply_to,
            deduplication_key=self._supplier_info_key(recipient, part_number),
        )
        result["draft_generation"] = {key: value for key, value in draft.items() if key not in {"subject", "body"}}
        return result

    @staticmethod
    def _supplier_info_key(recipient: str, part_number: str) -> str:
        # One consolidated follow-up per supplier and part; never re-ask field by field.
        return f"supplier-info:{recipient.strip().lower()}:{part_number.strip().upper()}"

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
        ensure_staging_recipient_allowed(recipient)
        subject = f"Re: RFQ: Part # {part_number.upper()} | Missing Tag & Trace Info"
        body = self._missing_fields_request(part_number, missing_fields)
        key = self._supplier_info_key(recipient, part_number)
        draft = await asyncio.to_thread(
            email_program_runtime.draft_supplier_request, subject, body, part_number, missing_fields
        )
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=key,
            mailbox="purchasing",
            recipient=recipient,
            subject=draft["subject"],
            body=draft["body"],
            reply_to=reply_to,
            entity_id=entity_id,
        )
        draft_generation = {key: value for key, value in draft.items() if key not in {"subject", "body"}}
        await repositories.records.record_automation_event(
            idempotency_key=f"{key}:draft",
            event_type="supplier_email_draft",
            entity_type="supplier_communication",
            entity_id=entity_id or queued["id"],
            status=draft["status"],
            result=json.dumps(draft_generation),
        )
        return {
            "mailbox": "purchasing",
            "recipient": recipient,
            "subject": subject,
            "reply_to": reply_to,
            "transmission_status": queued["status"],
            "communication_id": queued["id"],
            "outbox_id": queued["id"],
            "draft_generation": draft_generation,
        }

    def request_stale_supplier_confirmation(
        self,
        recipient: str,
        supplier_name: str,
        part_number: str,
        quantity: int,
        reply_to: Optional[str] = None,
        *,
        rfq_id: str | None = None,
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
        draft = email_program_runtime.draft_supplier_request(
            subject, body, part_number,
            ["availability", "price", "condition", "certification", "lead time", "quote validity"],
        )
        key = hashlib.sha256(json.dumps(
            [rfq_id, recipient.strip().lower(), part_number.strip().upper(), quantity, reply_to],
        ).encode("utf-8")).hexdigest() if rfq_id else None
        result = self._send(
            "purchasing", recipient, draft["subject"], draft["body"], reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"supplier-confirm:{key}" if key else None,
        )
        result["draft_generation"] = {
            key: value for key, value in draft.items() if key not in {"subject", "body"}
        }
        return result

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
        ensure_staging_recipient_allowed(recipient)
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

    def notify_suppliers_rfq_closed(
        self,
        part_number: str,
        offers: List[Dict[str, Any]],
        selected_supplier_email: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Thank non-selected suppliers so nobody is left hanging after a deal closes."""
        selected = (selected_supplier_email or "").strip().lower()
        recipients: List[tuple[str, Optional[str]]] = []
        seen: set[str] = set()
        for offer in offers or []:
            email = str(offer.get("supplier_email") or "").strip()
            key = email.lower()
            if not email or key == selected or key in seen or not self._is_valid_email(email):
                continue
            seen.add(key)
            recipients.append((email, offer.get("source_email_id")))
        limit = int(os.getenv("SUPPLIER_RFQ_WAVE_SIZE", "40"))
        part = part_number.strip().upper()
        results = []
        for email, source_id in recipients[:limit]:
            body = (
                "Hello,\n\n"
                f"Thank you for your quote on {part}! The customer elected to go with a different option for this "
                "requirement, but we look forward to working with you on the next one.\n\n"
                "While we have you, could you send over your latest full inventory list? "
                "We'd love to keep it on file for upcoming requirements.\n\n"
                "Best regards,\nWinged Tycoons Purchasing"
            )
            try:
                results.append(self._send(
                    "purchasing", email, f"Re: RFQ request: {part} - closed", body,
                    reply_to=source_id or None,
                    deduplication_key=f"supplier-closed:{email.lower()}:{part}",
                ))
            except Exception as exc:
                logger.warning("supplier_rfq_closed_failed part=%s supplier=%s error=%s", part, email, exc)
        return results

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
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        subject, body = self._purchase_order_notification_content(
            po_number, customer_name, customer_email, quote_id, items,
            previous_po_number, previous_quote_id, review_url,
        )
        return self._send("sales", recipient, subject, body, reply_to=None, attachments=attachments)

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
        attachments: List[Dict[str, Any]] | None = None,
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
        attachments: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        subject, body = self._purchase_order_notification_content(
            po_number, customer_name, customer_email, quote_id, items,
            previous_po_number, previous_quote_id, review_url,
        )
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        ensure_staging_recipient_allowed(recipient)
        serialized_attachments = _serialize_email_attachments(attachments)
        deduplication_key = hashlib.sha256(
            "\0".join((
                "sales", recipient.lower(), subject, body, "", "", quote_id,
                json.dumps(serialized_attachments, sort_keys=True),
            )).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            attachments=serialized_attachments,
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

    def send_shipment_tracking_link(
        self, recipient: str, shipment_id: str, public_token: str, company_name: str
    ) -> Dict[str, Any]:
        subject, body = self._shipment_tracking_content(shipment_id, public_token, company_name)
        return self._send("sales", recipient, subject, body, reply_to=None)

    def _shipment_tracking_content(
        self, shipment_id: str, public_token: str, company_name: str
    ) -> tuple[str, str]:
        portal_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3000")
        tracking_url = f"{portal_url.rstrip('/')}/track/{public_token}"
        body = enforce_customer_email_policy((
            "Hello,\n\n"
            f"Your Winged Tycoons shipment {shipment_id} is now being prepared. "
            "You can follow its status using this private tracking link:\n\n"
            f"{tracking_url}\n\n"
            "The tracking page will show carrier updates, latest location, and estimated delivery when available.\n\n"
            "Kind regards,\nWinged Tycoons Logistics Team"
        ), company_name)
        return f"Shipment tracking available - {shipment_id}", body

    async def send_shipment_tracking_link_async(
        self, repositories, recipient: str, shipment_id: str, public_token: str, company_name: str
    ) -> Dict[str, Any]:
        subject, body = self._shipment_tracking_content(shipment_id, public_token, company_name)
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        ensure_staging_recipient_allowed(recipient)
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
    ) -> Dict[str, Any]:
        subject = f"Winged Tycoons quotation {quote_id}"
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

        body, html_body = self.render_customer_quote_email(
            customer_name=customer_name,
            quote_id=quote_id,
            quote=quote_details,
            items=quote_items,
            quote_summary=quote_body,
        )
        if operations_store.storage_engine == "postgresql" and quote_details:
            with operations_store.transaction():
                result = self._send(
                    "sales", recipient, subject, body, reply_to=reply_to,
                    html_body=html_body,
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
                html_body=html_body,
                entity_id=quote_id, deduplication_key=f"customer-quote:{quote_id}",
            )
            self.schedule_customer_followup(
                recipient=recipient,
                customer_name=customer_name,
                quote_id=quote_id,
                reply_to=reply_to,
            )
        return {
            **result,
            "rendered_subject": subject,
            "rendered_body": body,
            "rendered_html_body": html_body,
        }

    @staticmethod
    def render_customer_quote_email(
        *,
        customer_name: str,
        quote_id: str,
        quote: Any,
        items: List[Any],
        quote_summary: str = "",
    ) -> tuple[str, str]:
        def value(item: Any, key: str, default: Any = None) -> Any:
            return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

        rows = []
        text_rows = []
        subtotal = 0.0
        for item in items:
            part_number = safe_display_text(value(item, "part_number", ""))
            description = safe_display_text(value(item, "description") or part_number)
            quantity = int(value(item, "quantity", 0) or 0)
            unit_price = float(value(item, "unit_price", 0) or 0)
            line_total = quantity * unit_price
            subtotal += line_total
            condition = safe_display_text(value(item, "condition") or "Not specified")
            certificate = safe_display_text(value(item, "certificate_type") or "Not specified")
            lead_time = value(item, "lead_time_days")
            lead_text = f"{int(lead_time)} days" if lead_time is not None else "To be confirmed"
            location = safe_display_text(
                value(item, "availability_location") or value(item, "unit_location") or "To be confirmed by supplier"
            )
            text_rows.append(
                f"{part_number} — {description}; Qty {quantity}; Condition {condition}; "
                f"Release document {certificate}; Lead time {lead_text}; Unit location {location}; "
                f"Unit price ${unit_price:,.2f}; Line total ${line_total:,.2f}"
            )
            rows.append(
                "<tr>"
                f"<td>{html_lib.escape(part_number)}<br><span>{html_lib.escape(description)}</span></td>"
                f"<td>{quantity}</td><td>{html_lib.escape(condition)}</td>"
                f"<td>{html_lib.escape(certificate)}</td><td>{html_lib.escape(lead_text)}</td>"
                f"<td>{html_lib.escape(location)}</td>"
                f"<td>${unit_price:,.2f}</td><td>${line_total:,.2f}</td>"
                "</tr>"
            )
        shipping = float(value(quote, "shipping_cost", 0) or 0) if quote else 0.0
        total = float(value(quote, "total_amount", subtotal + shipping) or subtotal + shipping) if quote else subtotal + shipping
        valid_until = safe_display_text(value(quote, "valid_until") or "Not specified") if quote else "Not specified"
        name = safe_display_text(customer_name or "Customer")
        text_body = (
            f"Dear {name},\n\n"
            f"Thank you for your request. Your quotation {quote_id} is ready.\n\n"
            "QUOTATION SUMMARY\n"
            f"Quote reference: {quote_id}\n"
            f"Valid through: {valid_until}\n"
            "Payment terms: Prepayment\n"
            "Notes: Unit ships same day upon PO and payment receipt.\n\n"
            "ITEMIZED PRICING\n"
            + "\n".join(text_rows)
            + f"\n\nSubtotal: ${subtotal:,.2f}\nShipping: ${shipping:,.2f}\nTotal: ${total:,.2f}\n\n"
            "Shipping is not included unless listed above. Release documents and supporting records are "
            "identified only as stated for each item; copies can be provided when available and verified.\n\n"
            "Please reply to this email with your purchase order or any questions. We will keep all "
            "quotation correspondence in this thread.\n\n"
            "Best regards,\nWinged Tycoons Sales Team"
        )
        safe_text_body = enforce_customer_email_policy(
            text_body, customer_name, satisfaction_question="Does this quotation meet your needs?"
        )
        html_body = (
            "<div style=\"font-family:Montserrat,Arial,sans-serif;color:#172033;max-width:900px;margin:auto\">"
            f"<p>Dear {html_lib.escape(name)},</p>"
            f"<p>Thank you for your request. Your quotation <strong>{html_lib.escape(quote_id)}</strong> is ready.</p>"
            "<h2 style=\"color:#8a6a19\">Quotation summary</h2>"
            f"<p><strong>Quote reference:</strong> {html_lib.escape(quote_id)}<br>"
            f"<strong>Valid through:</strong> {html_lib.escape(valid_until)}<br>"
            "<strong>Payment terms:</strong> Prepayment<br>"
            "<strong>Notes:</strong> Unit ships same day upon PO and payment receipt.</p>"
            "<h2 style=\"color:#8a6a19\">Itemized pricing</h2>"
            "<table style=\"border-collapse:collapse;width:100%\">"
            "<thead><tr>"
            + "".join(
                f"<th style=\"text-align:left;border-bottom:2px solid #d7dde5;padding:8px\">{label}</th>"
                for label in ("Part / description", "Qty", "Condition", "Release document", "Lead time", "Unit location", "Unit price", "Line total")
            )
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
            f"<p style=\"text-align:right\"><strong>Subtotal:</strong> ${subtotal:,.2f}<br>"
            f"<strong>Shipping:</strong> ${shipping:,.2f}<br>"
            f"<strong>Total:</strong> ${total:,.2f}</p>"
            "<p>Shipping is not included unless listed above. Release documents and supporting records are "
            "identified only as stated for each item; copies can be provided when available and verified.</p>"
            "<p>Please reply to this email with your purchase order or any questions. We will keep all "
            "quotation correspondence in this thread.</p>"
            "<p>Best regards,<br>Winged Tycoons Sales Team</p></div>"
        )
        return safe_text_body, html_body

    async def enqueue_customer_quote_async(
        self,
        repositories,
        *,
        recipient: str,
        quote_id: str,
        rfq_id: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        quote_items: List[Dict[str, Any]],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        ensure_staging_recipient_allowed(recipient)
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
            html_body=html_body,
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
            company_name=safe_display_text(customer_name),
        ))
        due = _next_customer_business_window(local_now + timedelta(days=final_chase_day()))
        task = await repositories.records.schedule_communication_task(
            task_key=chase_task_keys(quote_id)[0],
            task_type="customer_followup",
            mailbox="sales",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
            due_at=due.astimezone(timezone.utc),
            reply_to=reply_to,
        )
        return [task]

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
        name = safe_display_text(customer_name or "", fallback="")
        if not name:
            raise ValueError("Customer company name is required before acknowledging an RFQ.")
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
            lines.append(f"- **P/N:** `{pn}` | **Qty:** {qty_text} | **Condition:** {cond_text}")
            if "(assumed)" in qty_text:
                to_confirm.append(f"the quantity you need for {pn}")
            if not condition:
                to_confirm.append(f"your preferred condition for {pn}")
        if not lines:
            lines.append("- the requested parts")
        if not certifications:
            to_confirm.append("any certification you require (e.g. FAA 8130-3, EASA Form 1)")
        confirm_text = ""
        if to_confirm:
            confirm_text = (
                "**To quote exactly what you need, please confirm:**\n"
                + "\n".join(f"- {entry}" for entry in dict.fromkeys(to_confirm))
                + "\n\nNothing is on hold while you reply.\n\n"
            )
        portal = customer_portal_url()
        subject_pn = next(iter(seen), rfq_id)
        body = enforce_customer_email_policy((
            f"Hi **{name}**,\n\n"
            "Thanks for reaching out! We've received your inquiry (reference "
            f"`{rfq_id}`).\n\n"
            "Our sourcing team is already working on it to secure the best availability, trace, and pricing for you.\n\n"
            + "\n".join(lines)
            + "\n\n"
            + confirm_text
            + "---\n\n"
            "**Want live tracking on this requirement?**\n\n"
            f"View real-time status, review tag documentation, and manage your RFQs on the "
            f"Winged Tycoons Portal: {portal}\n\n"
            "We'll follow up in this thread shortly with complete options. Feel free to explore your dashboard in the meantime!\n\n"
            "Best regards,\n**Camila**\n*Winged Tycoons Team*"
        ), name)
        return self._send(
            "sales",
            recipient,
            f"Re: {subject_pn} – We're on it!",
            body,
            reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"rfq-ack:{rfq_id}",
        )

    def send_rfq_no_quote(
        self,
        *,
        rfq_id: str,
        recipient: str,
        customer_name: str | None,
        part_numbers: List[str],
        reply_to: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Politely tell the customer, in the original thread and once per RFQ, that we could not source the part."""
        if not recipient or not self._is_valid_email(recipient):
            return None
        lowered = recipient.lower()
        if "partsbase" in lowered or lowered.endswith("@wingedtycoons.com"):
            return None
        name = safe_display_text(customer_name or "", fallback="")
        if not name:
            raise ValueError("Customer company name is required before sending an RFQ update.")
        parts = [safe_display_text(str(p), fallback="").strip() for p in part_numbers]
        parts = [p for p in dict.fromkeys(parts) if p]
        part_text = ", ".join(f"P/N {p}" for p in parts) if parts else "the requested part"
        body = enforce_customer_email_policy((
            f"Hello {name},\n\n"
            f"Thank you for your request for quote {rfq_id} for {part_text}.\n\n"
            "We weren't able to source this part right now; we'll let you know if it becomes available.\n\n"
            "Best regards,\nWinged Tycoons Sales Team"
        ), name)
        return self._send(
            "sales",
            recipient,
            f"Re: Your request for quote {rfq_id}",
            body,
            reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"rfq-noquote:{rfq_id}",
        )

    def send_rfq_sourcing_update(
        self,
        *,
        recipient: str,
        customer_name: str,
        rfq_id: str,
        part_number: str,
        reply_to: Optional[str] = None,
        historical_offer_date: str | None = None,
        indicative_unit_price: float | None = None,
        supplier_contact_queued: bool = True,
    ) -> Dict[str, Any]:
        part = safe_display_text(part_number)
        if indicative_unit_price is not None and (
            not math.isfinite(indicative_unit_price) or indicative_unit_price <= 0
        ):
            raise ValueError("Indicative customer price must be a finite, positive USD amount.")
        historical_note = (
            f"For budgeting only, the indicative unit price is USD {indicative_unit_price:,.2f}. "
            "This is a non-binding reference, subject to current supplier confirmation; "
            "it is not a firm quotation or confirmed availability. "
            if indicative_unit_price is not None else ""
        )
        supplier_update = (
            "We have asked the supplier(s) to reconfirm current price, quantity, condition, release "
            "documentation, and lead time. "
            if supplier_contact_queued else
            "We are arranging supplier confirmation for current price, quantity, condition, release "
            "documentation, and lead time. "
        )
        body = enforce_customer_email_policy(
            f"Dear {safe_display_text(customer_name)},\n\n"
            f"We are still sourcing part {part} for request {rfq_id}. "
            f"{historical_note}"
            f"{supplier_update}"
            "We will send a firm quotation when a current offer is verified. "
            "There is no confirmed price or availability to commit to yet.\n\n"
            "Kind regards,\nWinged Tycoons Sales Team",
            customer_name,
        )
        return self._send(
            "sales",
            recipient,
            f"Re: Request for quote {rfq_id} - sourcing update",
            body,
            reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"rfq-sourcing-update:{rfq_id}:{part_number}",
        )

    def send_customer_information_response(
        self,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        request_text: str,
        reply_to: Optional[str] = None,
        communication_sentiment: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Reply in-thread to a customer asking for quote supporting details."""
        quote = db_service.get_quote(quote_id)
        if not quote:
            raise ValueError(f"Quote {quote_id} was not found for customer response.")
        items = db_service.get_quote_items(quote_id)
        attachments = _source_documents_for_customer_request(request_text, items)
        grounded_answer = customer_question_service.answer_from_quote(
            request_text, quote, items,
            source_documents=[item["filename"] for item in attachments] if attachments else None,
        )
        if not grounded_answer:
            raise ValueError("The customer question could not be answered from approved quote data.")
        sentiment_label = self._sentiment_label(communication_sentiment)
        tone_acknowledgement = {
            "positive": "Thank you for your kind message.",
            "negative": "Thank you for sharing your concern. We appreciate the opportunity to clarify.",
            "mixed": "Thank you for the context. We will keep the details below clear and specific.",
            "neutral": "Thank you for your question.",
        }[sentiment_label]
        body = enforce_customer_email_policy(
            _customer_inquiry_body(customer_name, tone_acknowledgement, quote_id, quote, grounded_answer),
            customer_name, satisfaction_question="Does this answer your question and provide everything you need?")
        html_body = _customer_html_from_text(body)
        return self._send(
            "sales",
            recipient,
            f"Re: Quotation {quote_id} - requested details",
            body,
            reply_to=reply_to,
            html_body=html_body,
            attachments=attachments,
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
        communication_sentiment: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        attachments = _source_documents_for_customer_request(request_text, items)
        grounded_answer = customer_question_service.answer_from_quote(
            request_text, quote, items,
            source_documents=[item["filename"] for item in attachments] if attachments else None,
        )
        if not grounded_answer:
            raise ValueError("The customer question could not be answered from approved quote data.")
        sentiment_label = self._sentiment_label(communication_sentiment)
        tone_acknowledgement = {
            "positive": "Thank you for your kind message.",
            "negative": "Thank you for sharing your concern. We appreciate the opportunity to clarify.",
            "mixed": "Thank you for the context. We will keep the details below clear and specific.",
            "neutral": "Thank you for your question.",
        }[sentiment_label]
        body = enforce_customer_email_policy(
            _customer_inquiry_body(customer_name, tone_acknowledgement, quote_id, quote, grounded_answer),
            customer_name, satisfaction_question="Does this answer your question and provide everything you need?")
        html_body = _customer_html_from_text(body)
        subject = f"Re: Quotation {quote_id} - requested details"
        return await self._enqueue_customer_reply_async(
            repositories, recipient, subject, body, reply_to, quote_id,
            attachments=attachments, html_body=html_body,
        )

    def send_customer_document_unavailable(
        self,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        quote_items = db_service.get_quote_items(quote_id)
        certificate_facts = [
            f"{item.part_number}: {item.certificate_type}"
            for item in quote_items if getattr(item, "certificate_type", None)
        ]
        certificate_text = (
            "The approved quote lists " + "; ".join(certificate_facts) + ". "
            if certificate_facts else ""
        )
        body = enforce_customer_email_policy(
            f"Dear {safe_display_text(customer_name)},\n\n"
            f"Regarding quotation {quote_id}, {certificate_text}"
            "The requested certificate or trace document is not available in the verified source files. "
            "We have sent this request to our team for document retrieval and validation. To avoid sending "
            "a document that may not match the quoted unit, we will follow up in this email thread once "
            "the correct file has been confirmed.\n\n"
            "Kind regards,\nWinged Tycoons Aviation Team",
            customer_name,
        )
        return self._send(
            "sales", recipient, f"Re: Quotation {quote_id} - document request", body,
            reply_to=reply_to,
        )

    async def send_customer_document_unavailable_async(
        self,
        repositories,
        *,
        recipient: str,
        customer_name: str,
        quote_id: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        quote_items = await repositories.records.list_by_payload_value(
            "quote_items", "quote_id", quote_id
        )
        certificate_facts = [
            f"{item.get('part_number')}: {item.get('certificate_type')}"
            for item in quote_items.values() if item.get("certificate_type")
        ]
        certificate_text = (
            "The approved quote lists " + "; ".join(certificate_facts) + ". "
            if certificate_facts else ""
        )
        body = enforce_customer_email_policy(
            f"Dear {safe_display_text(customer_name)},\n\n"
            f"Regarding quotation {quote_id}, {certificate_text}"
            "The requested certificate or trace document is not available in the verified source files. "
            "We have sent this request to our team for document retrieval and validation. To avoid sending "
            "a document that may not match the quoted unit, we will follow up in this email thread once "
            "the correct file has been confirmed.\n\n"
            "Kind regards,\nWinged Tycoons Aviation Team",
            customer_name,
        )
        return await self._enqueue_customer_reply_async(
            repositories, recipient, f"Re: Quotation {quote_id} - document request",
            body, reply_to, quote_id,
        )

    @staticmethod
    def _rfq_update_email(rfq_id: str, customer_name: str, customer_text: str, original_subject: str, quote_answer: str | None = None) -> tuple[str, str]:
        from services.customer_reply_routing import build_rfq_update_reply

        body = enforce_customer_email_policy(
            build_rfq_update_reply(rfq_id, customer_text, quote_answer), customer_name
        )
        base = re.sub(r"^\s*(?:(?:re|fw|fwd)\s*:\s*)+", "", original_subject or "", flags=re.IGNORECASE).strip()
        subject = f"Re: {base}" if base else f"Re: Your request for quote {rfq_id}"
        return subject, body

    def send_rfq_update_reply(
        self,
        *,
        recipient: str,
        customer_name: str,
        rfq_id: str,
        customer_text: str,
        original_subject: str,
        reply_to: Optional[str],
        inbound_message_id: str,
        quote_answer: str | None = None,
    ) -> Dict[str, Any]:
        """Reply in the customer's thread when they add details/questions to an existing RFQ."""
        subject, body = self._rfq_update_email(rfq_id, customer_name, customer_text, original_subject, quote_answer)
        return self._send(
            "sales",
            recipient,
            subject,
            body,
            reply_to=reply_to,
            entity_id=rfq_id,
            deduplication_key=f"rfq-update:{rfq_id}:{inbound_message_id}",
        )

    @staticmethod
    def _customer_receipt_email(customer_name: str, original_subject: str, purchase_order: bool) -> tuple[str, str]:
        context = (
            "We have received your purchase order and any attached supporting documents. "
            "Our team is validating the order; this acknowledgement is not order acceptance or a shipment confirmation."
            if purchase_order else
            "We have received your message. Our team is reviewing it and will respond in this email thread."
        )
        subject = re.sub(r"^\s*(?:re\s*:\s*)+", "", original_subject, flags=re.IGNORECASE).strip()
        body = enforce_customer_email_policy(
            f"Dear {safe_display_text(customer_name)},\n\n{context}\n\n"
            "Kind regards,\nWinged Tycoons Sales Team", customer_name,
        )
        return f"Re: {subject or 'Your message to Winged Tycoons'}", body

    def send_customer_receipt(self, *, recipient: str, customer_name: str, original_subject: str,
                              inbound_message_id: str, reply_to: str | None,
                              purchase_order: bool = False) -> Dict[str, Any]:
        subject, body = self._customer_receipt_email(customer_name, original_subject, purchase_order)
        return self._send(
            "sales", recipient, subject, body, reply_to=reply_to,
            entity_id=inbound_message_id,
            deduplication_key=f"customer-receipt:{inbound_message_id}",
        )

    async def send_customer_receipt_async(self, repositories, *, recipient: str, customer_name: str,
                                         original_subject: str, inbound_message_id: str,
                                         reply_to: str | None, purchase_order: bool = False) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        subject, body = self._customer_receipt_email(customer_name, original_subject, purchase_order)
        return await self._enqueue_customer_reply_async(
            repositories, recipient, subject, body, reply_to, inbound_message_id,
            deduplication_key=f"customer-receipt:{inbound_message_id}",
        )

    async def send_rfq_update_reply_async(
        self,
        repositories,
        *,
        recipient: str,
        customer_name: str,
        rfq_id: str,
        customer_text: str,
        original_subject: str,
        reply_to: Optional[str],
        inbound_message_id: str,
        quote_answer: str | None = None,
    ) -> Dict[str, Any]:
        if not self._is_valid_email(recipient):
            raise ValueError("Customer email is invalid. Email dispatch aborted.")
        ensure_staging_recipient_allowed(recipient)
        subject, body = self._rfq_update_email(rfq_id, customer_name, customer_text, original_subject, quote_answer)
        return await self._enqueue_customer_reply_async(
            repositories, recipient, subject, body, reply_to, rfq_id,
            deduplication_key=f"rfq-update:{rfq_id}:{inbound_message_id}",
        )

    async def _enqueue_customer_reply_async(
        self, repositories, recipient: str, subject: str, body: str, reply_to: Optional[str], entity_id: str,
        deduplication_key: str | None = None,
        attachments: List[Dict[str, Any]] | None = None,
        html_body: str | None = None,
    ) -> Dict[str, Any]:
        ensure_staging_recipient_allowed(recipient)
        serialized_attachments = _serialize_email_attachments(attachments)
        quote_id = entity_id
        deduplication_key = deduplication_key or hashlib.sha256(
            "\0".join((
                "sales", recipient.lower(), subject, body, html_body or "", reply_to or "", "", quote_id,
                json.dumps(serialized_attachments, sort_keys=True),
            )).encode("utf-8")
        ).hexdigest()
        queued = await repositories.records.enqueue_outbox_message(
            deduplication_key=deduplication_key,
            mailbox="sales",
            recipient=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
            attachments=serialized_attachments,
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

    @staticmethod
    def _sentiment_label(sentiment: Dict[str, Any] | None) -> str:
        if not isinstance(sentiment, dict):
            return "neutral"
        label = sentiment.get("label")
        try:
            confidence = float(sentiment.get("confidence", 0.0))
        except (TypeError, ValueError):
            return "neutral"
        if label not in {"positive", "neutral", "negative", "mixed"} or confidence < 65:
            return "neutral"
        return label

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
            company_name=safe_display_text(customer_name),
        ))
        due = _next_customer_business_window(local_now + timedelta(days=final_chase_day()))
        return self._schedule_communication_task(
            task_key=chase_task_keys(quote_id)[0],
            task_type="customer_followup",
            mailbox="sales",
            recipient=recipient,
            subject=template.subject,
            body=template.body,
            due_at=due.astimezone(timezone.utc).isoformat(),
            reply_to=reply_to,
        )

    def cancel_customer_followups(self, quote_id: str) -> None:
        for task_key in self._customer_followup_task_keys(quote_id):
            if operations_store.storage_engine == "postgresql":
                operations_store.cancel_communication_task(task_key)
            else:
                supplier_db.cancel_communication_task(task_key)

    @staticmethod
    def _customer_followup_task_keys(quote_id: str) -> list[str]:
        keys = chase_task_keys(quote_id)
        return list(dict.fromkeys([f"customer-followup:{quote_id}", *keys]))

    async def cancel_customer_followups_async(self, repositories, quote_id: str) -> None:
        for task_key in self._customer_followup_task_keys(quote_id):
            await repositories.records.cancel_communication_task(task_key)

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
        supplier_sentiment: Dict[str, Any] | None = None,
        currency: str = "USD",
        target_discount_percentage: float | None = None,
    ) -> Dict[str, Any]:
        if currency.strip().upper() != "USD":
            raise ValueError("Automated supplier discount requests support USD offers only.")
        if target_discount_percentage is not None and not 0 < target_discount_percentage <= 5:
            raise ValueError("Automated supplier discount requests are capped at 5%.")
        max_rounds = min(5, max(1, int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "3"))))
        if round_number > max_rounds:
            return {"status": "LIMIT_REACHED", "round": round_number}
        template = compose_supplier_discount_request(SupplierDiscountData(
            supplier_contact=safe_display_text(supplier_name),
            recipient_email=recipient,
            part_number=part_number.upper(),
            quantity=quantity,
            quoted_price=unit_cost,
            currency="USD",
            target_discount_percentage=target_discount_percentage,
            supplier_sentiment=self._sentiment_label(supplier_sentiment),
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
        supplier_sentiment: Dict[str, Any] | None = None,
        currency: str = "USD",
        target_discount_percentage: float | None = None,
    ) -> Dict[str, Any]:
        if currency.strip().upper() != "USD":
            raise ValueError("Automated supplier discount requests support USD offers only.")
        if target_discount_percentage is not None and not 0 < target_discount_percentage <= 5:
            raise ValueError("Automated supplier discount requests are capped at 5%.")
        max_rounds = min(5, max(1, int(os.getenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "3"))))
        if round_number > max_rounds:
            return {"status": "LIMIT_REACHED", "round": round_number}
        template = compose_supplier_discount_request(SupplierDiscountData(
            supplier_contact=safe_display_text(supplier_name),
            recipient_email=recipient,
            part_number=part_number.upper(),
            quantity=quantity,
            quoted_price=unit_cost,
            currency="USD",
            target_discount_percentage=target_discount_percentage,
            supplier_sentiment=self._sentiment_label(supplier_sentiment),
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
        if task.get("task_type") == "customer_followup" and not self._is_current_customer_followup(task):
            self._cancel_communication_task(str(task["task_key"]))
            return {"transmission_status": "CANCELLED", "communication_task_id": task.get("id")}
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
        if task.get("task_type") == "customer_followup" and not self._is_current_customer_followup(task):
            await repositories.records.cancel_communication_task(str(task["task_key"]))
            return {"transmission_status": "CANCELLED", "communication_task_id": task.get("id")}
        mailbox = str(task.get("mailbox") or "sales")
        recipient = str(task.get("recipient") or "")
        if mailbox not in MAILBOXES:
            raise ValueError("Unknown outbound mailbox.")
        if not self._is_valid_email(recipient):
            raise ValueError("Recipient email is invalid. Email dispatch aborted.")
        ensure_staging_recipient_allowed(recipient)
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

    @staticmethod
    def _is_current_customer_followup(task: Dict[str, Any]) -> bool:
        body = str(task.get("body") or "").casefold()
        return (
            "does this quotation meet your needs?" in body
            and customer_portal_url().casefold() in body
        )

    @staticmethod
    def _cancel_communication_task(task_key: str) -> None:
        if operations_store.storage_engine == "postgresql":
            operations_store.cancel_communication_task(task_key)
        else:
            supplier_db.cancel_communication_task(task_key)

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
        html_body: str | None = None,
        attachments: List[Dict[str, Any]] | None = None,
        communication_task_id: str | None = None,
        entity_id: str | None = None,
        deduplication_key: str | None = None,
    ) -> Dict[str, Any]:
        ensure_staging_recipient_allowed(recipient)
        if operations_store.storage_engine == "postgresql":
            serialized_attachments = _serialize_email_attachments(attachments)
            dedupe_material = "\0".join((
                mailbox, recipient.lower(), subject, body, html_body or "", reply_to or "",
                communication_task_id or "", entity_id or "",
                json.dumps(serialized_attachments, sort_keys=True),
            ))
            deduplication_key = deduplication_key or hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()
            if not self._is_valid_email(recipient):
                raise ValueError("Recipient email is invalid. Email dispatch aborted.")
            queued = operations_store.enqueue_outbox_message(
                deduplication_key=deduplication_key,
                mailbox=mailbox,
                recipient=recipient,
                subject=subject,
                body=body,
                html_body=html_body,
                attachments=serialized_attachments,
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
            threaded = send_message(
                mailbox, recipient, subject, body, reply_to=reply_to,
                html_body=html_body, attachments=attachments,
            )
            result["transmission_status"] = "SENT"
            result["threaded"] = threaded is not False
            if reply_to and threaded is False:
                self._flag_unthreaded_reply(reply_to, recipient, subject, reply_to)
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

    @staticmethod
    def _unthreaded_review_values(key: str, recipient: str, subject: str, entity_id: Any) -> dict[str, Any]:
        return {
            "idempotency_key": f"unthreaded:{key}",
            "task": "email_thread_check",
            "source_text": subject or "",
            "extraction": {"recipient": recipient, "subject": subject},
            "reason": "Original email thread not found; reply was sent as a new email. Please check with the client.",
            "entity_id": str(entity_id) if entity_id else None,
        }

    def _flag_unthreaded_reply(self, key: str, recipient: str, subject: str, entity_id: Any) -> None:
        logger.warning("email_sent_unthreaded recipient=%s subject=%s", recipient, subject)
        try:
            operations_store.enqueue_operator_review(**self._unthreaded_review_values(key, recipient, subject, entity_id))
        except Exception:
            logger.exception("Could not flag unthreaded reply key=%s", key)

    def dispatch_outbox_once(self, *, limit: int = 25) -> dict[str, int]:
        if operations_store.storage_engine != "postgresql":
            return {"sent": 0, "failed": 0}
        operations_store.recover_stale_outbox_messages()
        sent = 0
        failed = 0
        for message in operations_store.claim_outbox_messages(limit=limit):
            payload = message.get("payload") or {}
            body = payload.get("body", "") if isinstance(payload, dict) else str(payload)
            html_body = payload.get("html_body") if isinstance(payload, dict) else None
            try:
                attachments = _deserialize_email_attachments(
                    payload.get("attachments") if isinstance(payload, dict) else None
                )
                threaded = send_message(
                    message["mailbox"],
                    message["recipient"],
                    message["subject"],
                    body,
                    reply_to=message.get("reply_to"),
                    html_body=html_body,
                    attachments=attachments,
                )
                if message.get("reply_to") and threaded is False:
                    self._flag_unthreaded_reply(
                        str(message["id"]), message["recipient"], message["subject"], message.get("entity_id")
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
            html_body = payload.get("html_body") if isinstance(payload, dict) else None
            error = None
            retryable = False
            threaded = True
            try:
                attachments = _deserialize_email_attachments(
                    payload.get("attachments") if isinstance(payload, dict) else None
                )
                threaded = await asyncio.to_thread(
                    send_message,
                    message["mailbox"],
                    message["recipient"],
                    message["subject"],
                    body,
                    reply_to=message.get("reply_to"),
                    html_body=html_body,
                    attachments=attachments,
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
                    if message.get("reply_to") and threaded is False:
                        await repositories.records.enqueue_operator_review(
                            **self._unthreaded_review_values(
                                str(message["id"]), message["recipient"], message["subject"], message.get("entity_id")
                            )
                        )
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

    _FIELD_EXAMPLES = {
        "tag": ("Tag/Doc Type", "e.g., FAA 8130-3, Dual Release, CoC"),
        "cert": ("Tag/Doc Type", "e.g., FAA 8130-3, Dual Release, CoC"),
        "doc": ("Tag/Doc Type", "e.g., FAA 8130-3, Dual Release, CoC"),
        "trace": ("Traceability", "e.g., 121 / 135 / OEM Trace"),
        "warrant": ("Warranty", "e.g., 30 Days / 90 Days / Standard"),
        "lead": ("Lead Time", "e.g., Same-day dispatch / X days"),
        "price": ("Unit Price", "e.g., USD per unit"),
        "cost": ("Unit Price", "e.g., USD per unit"),
        "condition": ("Condition", "e.g., NE / OH / SV / AR"),
        "quantity": ("Quantity Available", "e.g., 2 EA"),
    }

    def _missing_fields_request(self, part_number: str, missing_fields: List[str]) -> str:
        rows: Dict[str, str] = {}
        for field in missing_fields:
            lowered = str(field).casefold()
            label, example = next(
                (value for key, value in self._FIELD_EXAMPLES.items() if key in lowered),
                (str(field).strip().title(), "Please confirm"),
            )
            rows.setdefault(label, example)
        bullets = "\n".join(f"- {label}: Pending – {example}" for label, example in rows.items())
        return (
            "Hi there,\n\n"
            "Thank you so much for the quick response and competitive offer on this unit"
            f" (P/N {part_number.upper()}) - we really appreciate working with your team!\n\n"
            "To help us finalize this option for our client, could you quickly confirm the missing details below?\n\n"
            f"{bullets}\n\n"
            "Please attach any certificate, trace document, or shop report to this same email thread.\n\n"
            "Once confirmed, we can move forward with presenting this to our end buyer.\n\n"
            "---\n\n"
            "While we review this unit, could you also send over your latest full stock list? "
            "We'd love to keep it on file for upcoming requirements.\n\n"
            "Thanks again for your excellent help!\n\n"
            "Best regards,\nWinged Tycoons Sourcing Team"
        )


communication_service = CommunicationService()
