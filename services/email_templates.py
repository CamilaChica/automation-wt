"""Deterministic outbound email templates with strict Pydantic contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    quoted_price: float = Field(..., ge=0)


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


def customer_quote(data: CustomerQuoteData) -> EmailPayload:
    subject = f"Quotation {data.quote_number} - Part Number {data.part_number}"
    attachment_text = ""
    if data.attachments:
        attachment_text = f"\n- Attachments: {', '.join(str(doc) for doc in data.attachments)}"

    body = (
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
    )
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
    body = (
        f"Dear {data.supplier_contact},\n\n"
        f"Thank you for providing the initial quotation for PN {data.part_number} at ${data.quoted_price:,.2f} per unit.\n\n"
        "We are actively working to secure this order for our customer. Could you please confirm if you can offer your best commercial price, best possible net price, or any volume discount for this requirement?\n\n"
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
    body = (
        f"Hi {data.contact_name},\n\n"
        f"I wanted to follow up on the quotation ({data.quote_number}) we sent recently for Part Number {data.part_number}.\n\n"
        "Please let us know if you are still looking to proceed or if you have any questions regarding pricing, lead times, or certification requirements. We are happy to adjust specifications or hold the sourcing information while you confirm.\n\n"
        "Best regards,\n\n"
        "Winged Tycoons Aviation Team"
    )
    return EmailPayload(message_type="CUSTOMER_FOLLOWUP", recipient_email=data.recipient_email, subject=subject, body=body)
