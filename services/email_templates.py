"""Deterministic outbound email templates with strict Pydantic contracts."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from services.email_context import safe_display_text


EmailType = Literal[
    "CUSTOMER_QUOTE",
    "SUPPLIER_RFQ",
    "SUPPLIER_DISCOUNT_REQUEST",
    "SUPPLIER_VERIFICATION",
    "CUSTOMER_FOLLOWUP",
]


class EmailPayload(BaseModel):
    message_type: EmailType
    recipient_email: str = Field(..., min_length=3)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)

    @field_validator("recipient_email")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        if "@" not in value or " " in value:
            raise ValueError("recipient_email must be a valid email address")
        return value.strip()


class CustomerQuoteData(BaseModel):
    contact_name: str
    recipient_email: str
    quote_number: str
    part_number: str
    description: str
    quantity: int = Field(..., gt=0)
    uom: str = Field(default="EA")
    condition: str
    certification: str
    unit_price: float = Field(..., ge=0)
    lead_time: str
    valid_until: str
    attachments: list[str] = Field(default_factory=list)
    company_name: str | None = None


class SupplierRFQData(BaseModel):
    supplier_contact: str
    recipient_email: str
    part_number: str
    quantity: int = Field(..., gt=0)
    condition_requested: str
    certification_requested: str


class SupplierDiscountData(BaseModel):
    supplier_contact: str
    recipient_email: str
    part_number: str
    quantity: int = Field(..., gt=0)
    quoted_price: float = Field(..., ge=0, allow_inf_nan=False)
    currency: Literal["USD"] = "USD"
    target_discount_percentage: float | None = Field(
        None, gt=0, le=5, allow_inf_nan=False
    )
    supplier_sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None


class SupplierVerificationData(BaseModel):
    supplier_contact: str
    recipient_email: str
    part_number: str
    quantity: int = Field(..., gt=0)
    po_number: str


class CustomerFollowupData(BaseModel):
    contact_name: str
    recipient_email: str
    part_number: str
    quote_number: str
    company_name: str | None = None


def customer_portal_url() -> str:
    url = os.getenv(
        "CUSTOMER_PORTAL_URL",
        "https://portal.wingedtycoons.com/customer-portal",
    ).strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError("CUSTOMER_PORTAL_URL must be an absolute HTTP(S) URL.")
    return url


def enforce_customer_email_policy(
    body: str,
    company_name: str,
    *,
    satisfaction_question: str | None = None,
) -> str:
    company = safe_display_text(company_name, fallback="")
    if not company:
        raise ValueError("Customer company name is required before sending an email.")

    content = str(body or "").strip()
    content = re.sub(r"^(?:Dear|Hi|Hello)\b[^\n]*\n+", "", content, count=1, flags=re.IGNORECASE)
    greeting = "Dear Customer," if "@" in company else f"Dear {company}'s team!"

    additions = []
    if satisfaction_question and satisfaction_question.casefold() not in content.casefold():
        additions.append(satisfaction_question)
    portal_url = customer_portal_url()
    if portal_url not in content:
        additions.append(
            f"Please use our customer portal to review your request, quotation, or shipment updates: {portal_url}"
        )

    if additions:
        closing = re.search(
            r"(?im)^(?:best regards|kind regards|warm regards|sincerely|regards)[,!]?\s*$",
            content,
        )
        insert_at = closing.start() if closing else len(content)
        before, after = content[:insert_at].rstrip(), content[insert_at:].lstrip()
        addition_text = "\n\n".join(additions)
        content = f"{before}\n\n{addition_text}" + (f"\n\n{after}" if after else "")

    return f"{greeting}\n\n{content}".rstrip()


def customer_quote(data: CustomerQuoteData) -> EmailPayload:
    subject = f"Quotation {data.quote_number} - Part Number {data.part_number}"
    attachment_text = ""
    if data.attachments:
        attachment_text = f"\n- Attachments: {', '.join(str(doc) for doc in data.attachments)}"

    body = enforce_customer_email_policy((
        f"Dear {data.contact_name},\n\n"
        "Thank you for contacting Winged Tycoons. We are pleased to offer the following quotation for your review:\n\n"
        f"- Part Number: {data.part_number}\n"
        f"- Description: {data.description}\n"
        f"- Quantity: {data.quantity} {data.uom}\n"
        f"- Condition: {data.condition}\n"
        f"- Certification: {data.certification}\n"
        f"- Unit Price: ${data.unit_price:,.2f} USD\n"
        f"- Lead Time: {data.lead_time}\n"
        f"- Quote Validity: Valid until {data.valid_until}{attachment_text}\n\n"
        "Please let us know if you would like to proceed with a purchase order or if you have any questions regarding delivery or specifications.\n\n"
        "Best regards,\n\n"
        "Winged Tycoons Aviation Team\n"
        "rfq@wingedtycoons.com"
    ), data.company_name or data.contact_name, satisfaction_question="Does this quotation meet your needs?")
    return EmailPayload(message_type="CUSTOMER_QUOTE", recipient_email=data.recipient_email, subject=subject, body=body)


def supplier_rfq(data: SupplierRFQData) -> EmailPayload:
    subject = f"RFQ - PN {data.part_number} - Qty {data.quantity}"
    body = (
        f"Dear {data.supplier_contact},\n\n"
        "Winged Tycoons is currently sourcing the following component and requesting availability and commercial pricing:\n\n"
        f"- Part Number: {data.part_number}\n"
        f"- Requested Quantity: {data.quantity}\n"
        f"- Requested Condition: {data.condition_requested}\n"
        f"- Certification Required: {data.certification_requested}\n\n"
        "Please reply with your best commercial offer including:\n"
        "1. Unit Price (USD)\n"
        "2. Available Quantity\n"
        "3. Condition & Traceability/Certification\n"
        "4. Lead Time & Shipping Location\n"
        "5. Quote Expiration Date\n\n"
        "Thank you for your prompt response.\n\n"
        "Purchasing Team | Winged Tycoons"
    )
    return EmailPayload(message_type="SUPPLIER_RFQ", recipient_email=data.recipient_email, subject=subject, body=body)


def supplier_discount_request(data: SupplierDiscountData) -> EmailPayload:
    subject = f"Commercial Request - PN {data.part_number} (Qty: {data.quantity})"
    acknowledgement = {
        "positive": "Thank you for your helpful quotation.",
        "neutral": "Thank you for providing the initial quotation.",
        "negative": "Thank you for clarifying your position. We appreciate your time.",
        "mixed": "Thank you for the quotation and for sharing the relevant context.",
    }.get(data.supplier_sentiment, "Thank you for providing the initial quotation.")
    if data.target_discount_percentage is None:
        negotiation_request = (
            "We are actively working to secure this order for our customer. Could you please confirm if you can "
            "offer your best commercial price, best possible net price, or any volume discount for this requirement?"
        )
    else:
        target_price = data.quoted_price * (1 - data.target_discount_percentage / 100)
        negotiation_request = (
            "We are actively working to secure this order for our customer. Could you please confirm whether you "
            f"can offer a {data.target_discount_percentage:g}% discount, bringing the target unit price to "
            f"${target_price:,.2f} {data.currency} for this quantity? This is a request for your consideration "
            "only and does not authorize an order."
        )
    body = (
        f"Dear {data.supplier_contact},\n\n"
        f"{acknowledgement} Your initial quotation was PN {data.part_number} at "
        f"${data.quoted_price:,.2f} {data.currency} per unit.\n\n"
        f"{negotiation_request}\n\n"
        "We appreciate your support and look forward to finalizing this purchase.\n\n"
        "Best regards,\n\n"
        "Purchasing Team | Winged Tycoons"
    )
    return EmailPayload(message_type="SUPPLIER_DISCOUNT_REQUEST", recipient_email=data.recipient_email, subject=subject, body=body)


def supplier_verification(data: SupplierVerificationData) -> EmailPayload:
    subject = f"URGENT - Availability Confirmation Required - PN {data.part_number}"
    body = (
        f"Dear {data.supplier_contact},\n\n"
        f"We have received a purchase order ({data.po_number}) from our customer for the following unit:\n\n"
        f"- Part Number: {data.part_number}\n"
        f"- Quantity: {data.quantity}\n\n"
        "Please confirm immediately:\n"
        "1. The units are currently in stock and available for immediate dispatch.\n"
        "2. The quoted price and condition remain valid.\n"
        "3. The requested airworthiness certification is ready.\n\n"
        "Please reply to confirm availability so we can issue our formal order.\n\n"
        "Best regards,\n\n"
        "Operations Team | Winged Tycoons"
    )
    return EmailPayload(message_type="SUPPLIER_VERIFICATION", recipient_email=data.recipient_email, subject=subject, body=body)


def customer_followup(data: CustomerFollowupData) -> EmailPayload:
    subject = f"Following up on Quote {data.quote_number} - PN {data.part_number}"
    body = enforce_customer_email_policy((
        f"Hi {data.contact_name},\n\n"
        f"I wanted to follow up on the quotation ({data.quote_number}) we sent recently for Part Number {data.part_number}.\n\n"
        "Does this quotation meet your needs? Please let us know if you have any questions about pricing, lead time, or certification.\n\n"
        "Best regards,\n\n"
        "Winged Tycoons Aviation Team"
    ), data.company_name or data.contact_name, satisfaction_question="Does this quotation meet your needs?")
    return EmailPayload(message_type="CUSTOMER_FOLLOWUP", recipient_email=data.recipient_email, subject=subject, body=body)
