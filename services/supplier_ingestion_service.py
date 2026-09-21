import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.supplier_database import supplier_db
from services.supplier_email_extractor import SupplierEmailExtractor


class SupplierEmailIngestionService:
    def __init__(self):
        self.extractor = SupplierEmailExtractor()

    def ingest_email(self, email_text: str, mailbox: str = "purchasing", message_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            extracted = self.extractor.extract(email_text)
            if not extracted.get("part_number"):
                return {"success": False, "error": "No part number detected in email."}

            sender = ""
            subject = ""
            for line in email_text.splitlines():
                if line.lower().startswith("from:"):
                    sender = line.split(":", 1)[1].strip()
                elif line.lower().startswith("subject:"):
                    subject = line.split(":", 1)[1].strip()

            supplier_name = extracted.get("supplier_name") or "Unknown Supplier"
            supplier_email = extracted.get("supplier_email") or sender
            part_number = extracted.get("part_number")
            quantity = extracted.get("quantity_available") or 1
            unit_cost = extracted.get("unit_cost") or 0.0
            certificate = extracted.get("certificate_type")
            lead_time = extracted.get("lead_time_days") or 3
            condition = extracted.get("condition_code") or "NE"
            source_email_id = message_id or f"EMAIL-{uuid.uuid4().hex[:12].upper()}"

            supplier_db.save_email(
                mailbox=mailbox,
                message_id=source_email_id,
                sender=supplier_email,
                subject=subject or f"Supplier Quote for {part_number}",
                body=email_text,
            )

            supplier_db.save_supplier_offer(
                supplier_name=supplier_name,
                supplier_email=supplier_email,
                part_number=part_number,
                quantity_available=quantity,
                unit_cost=float(unit_cost),
                certificate_type=certificate,
                lead_time_days=int(lead_time),
                approval_status=extracted.get("approval_status", "Approved"),
                condition_code=condition,
                source_email_id=source_email_id,
                confidence=float(extracted.get("confidence", 0.9)),
            )

            return {
                "success": True,
                "supplier_name": supplier_name,
                "part_number": part_number,
                "quantity_available": quantity,
                "unit_cost": float(unit_cost),
                "certificate_type": certificate,
                "lead_time_days": int(lead_time),
                "source_email_id": source_email_id,
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {"success": False, "error": str(exc)}
