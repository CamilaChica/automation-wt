from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentMetadata, AgentResponse
from services.communication_service import communication_service

class CustomerCommunicationAgent(BaseAgent):
    def __init__(self):
        metadata = AgentMetadata(
            name="CustomerCommunicationAgent",
            role="Customer Relationship Communication Specialist",
            objective="Draft and transmit professional communications regarding quote details to clients.",
            system_instruction=(
                "You draft commercial correspondences. Be courteous, clear, and professional. "
                "Include breakdown of items, price, lead time, and reference ID. "
                "Output transmission log and email draft content."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "quote_details": {
                        "type": "object",
                        "properties": {
                            "quote_id": {"type": "string"},
                            "total_amount": {"type": "number"},
                            "pdf_summary": {"type": "string"}
                        },
                        "required": ["quote_id", "total_amount"]
                    }
                },
                "required": ["customer_email", "customer_name", "quote_details"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "communication_logged": {"type": "boolean"},
                    "transmission_status": {"type": "string"},
                    "formatted_body": {"type": "string"}
                },
                "required": ["communication_logged", "transmission_status", "formatted_body"]
            },
            available_tools=["email_sender_service"],
            permissions=["send_emails"],
            escalation_rules=[],
            prompt_templates={
                "default": "You draft commercial correspondences. Be courteous, clear, and professional. Include breakdown of items, price, lead time, and reference ID. Output transmission log and email draft content.",
                "customer_quote": "Compose a polished customer quote email with any required attachments and price summary.",
            }
        )
        super().__init__(metadata)

    def _format_quote_summary(self, quote_details: Dict[str, Any]) -> str:
        quote_id = quote_details.get("quote_id", "")
        total = float(quote_details.get("total_amount", 0.0) or 0.0)
        subtotal = float(quote_details.get("subtotal", total) or 0.0)
        items = quote_details.get("items") or []

        lines = [
            f"Quote ID: {quote_id}",
            f"Subtotal: ${subtotal:,.2f}",
            "Shipping: customer-selected, not quoted by Winged Tycoons",
            f"Total: ${total:,.2f}",
            "",
            "Line items:",
        ]

        for item in items:
            part = item.get("part_number", "N/A")
            qty = item.get("quantity", 0)
            uom = item.get("uom") or "EA"
            unit = float(item.get("unit_price", 0.0) or 0.0)
            line_total = float(qty) * unit
            attachments = item.get("attachments") or []
            attachment_text = ""
            if attachments:
                attachment_text = " | Attachments: " + ", ".join(str(doc) for doc in attachments)
            lines.append(f"- {part} | Qty {qty} {uom} | Unit price ${unit:,.2f} | Line total ${line_total:,.2f}{attachment_text}")

        if not items:
            summary = quote_details.get("pdf_summary") or quote_details.get("formatted_pdf_summary")
            if summary:
                lines.extend(["", summary])

        return "\n".join(lines).strip()

    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        email = inputs.get("customer_email", "")
        name = inputs.get("customer_name", "")
        details = inputs.get("quote_details", {})
        reply_to = inputs.get("reply_to")

        quote_id = details.get("quote_id", "")
        total = details.get("total_amount", 0.0)
        summary = self._format_quote_summary(details)

        email_body = (
            f"Dear {name},\n\n"
            f"Thank you for contacting Winged Tycoons. We are pleased to provide you with the requested "
            f"sales quote details. Please see proposal reference {quote_id} below:\n\n"
            f"{summary}\n\n"
            f"Should you wish to place this order, please reply directly to this email or contact us at "
            f"sales@wingedtycoons.com.\n\n"
            f"Best regards,\n\n"
            f"Winged Tycoons Sales Team"
        )

        transmission = communication_service.send_customer_quote(
            recipient=email,
            customer_name=name,
            quote_id=quote_id,
            quote_summary=summary,
            reply_to=reply_to,
            quote_items=details.get("items") or None,
        )

        return AgentResponse(
            success=True,
            data={
                "communication_logged": True,
                "transmission_status": transmission["transmission_status"],
                "formatted_body": email_body
            }
        )

    def generate_quote_email(self, quote_data: dict) -> str:
        """Generate a quote email body using approved quote data.

        Args:
            quote_data: Dictionary containing approved quotation fields such as
                'quote_id', 'total_amount', and 'pdf_summary'.
        Returns:
            Formatted email body string.
        """
        quote_id = quote_data.get('quote_id', '')
        total = quote_data.get('total_amount', 0.0)
        pdf = quote_data.get('pdf_summary', '')
        return (
            f"Dear Customer,\n\n"
            f"Thank you for your interest. Please find the approved quotation details below:\n"
            f"Quote Reference: {quote_id}\n"
            f"Total Amount: ${total:,.2f}\n\n"
            f"{pdf}\n\n"
            f"If you wish to proceed, kindly reply to this email or contact our sales team.\n\n"
            f"Best regards,\nWinged Tycoons Sales Team"
        )

    def generate_status_update(self, status_data: dict) -> str:
        """Generate a status update email using order status information.

        Args:
            status_data: Dictionary with keys like 'order_id', 'status',
                'estimated_delivery'.
        Returns:
            Formatted status update string.
        """
        order_id = status_data.get('order_id', '')
        status = status_data.get('status', '')
        eta = status_data.get('estimated_delivery', '')
        return (
            f"Dear Customer,\n\n"
            f"We would like to provide an update on your order {order_id}.\n"
            f"Current status: {status}.\n"
            f"Estimated delivery date: {eta}.\n\n"
            f"Please let us know if you have any questions.\n\n"
            f"Best regards,\nWinged Tycoons Support Team"
        )

    def generate_shipping_notification(self, shipping_data: dict) -> str:
        """Generate a shipping notification email using approved shipping details.

        Args:
            shipping_data: Dictionary containing 'order_id', 'tracking_number',
                'carrier', and 'expected_arrival'.
        Returns:
            Formatted shipping notification string.
        """
        order_id = shipping_data.get('order_id', '')
        tracking = shipping_data.get('tracking_number', '')
        carrier = shipping_data.get('carrier', '')
        arrival = shipping_data.get('expected_arrival', '')
        return (
            f"Dear Customer,\n\n"
            f"Your order {order_id} has been shipped via {carrier}.\n"
            f"Tracking Number: {tracking}.\n"
            f"Expected arrival date: {arrival}.\n\n"
            f"You can track your shipment using the provided tracking number.\n\n"
            f"Thank you for choosing Winged Tycoons.\n\n"
            f"Best regards,\nWinged Tycoons Logistics Team"
        )

    def generate_clarification_request(self, missing_fields: list, context: dict) -> str:
        """Generate a clarification request email when required data is missing.

        Args:
            missing_fields: List of field names that are missing or incomplete.
            context: Additional context to include in the request (e.g., quote_id).
        Returns:
            Formatted clarification request string.
        """
        fields_formatted = ", ".join(missing_fields)
        reference = context.get('quote_id') or context.get('order_id', '')
        reference_line = f"Reference ID: {reference}\n" if reference else ""
        return (
            f"Dear Customer,\n\n"
            f"We are preparing your documentation but require additional information to proceed.\n"
            f"Missing/Incomplete fields: {fields_formatted}.\n"
            f"{reference_line}"
            f"Please provide the required details at your earliest convenience.\n\n"
            f"Thank you,\nWinged Tycoons Team"
        )
