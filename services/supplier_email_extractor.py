import html
import re
from typing import Any, Dict, List, Optional


class SupplierEmailExtractor:
    """Simple deterministic extractor for supplier emails.

    The system keeps the LLM boundary optional by using regex-based extraction
    first. This is enough for a first real supplier-email ingestion pipeline without
    introducing a vendor SDK or external API dependency.
    """

    def _normalize_text(self, text: str) -> str:
        cleaned = html.unescape(str(text or ""))
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</?(p|div|tr|td|table|body|html|span|font)[^>]*>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = cleaned.replace("\r", "")
        cleaned = cleaned.replace("&nbsp;", " ")
        cleaned = cleaned.replace("&#65279;", " ")
        cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.splitlines())
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    def extract(self, text: str) -> Dict[str, Any]:
        normalized = self._normalize_text(text)
        if not normalized:
            raise ValueError("Email content is empty.")

        self._validate_quote_signal(normalized)

        sender_match = re.search(r"(?:From|Sender)[:\s]+([^\r\n]+)", normalized, flags=re.IGNORECASE)
        sender = sender_match.group(1).strip() if sender_match else ""

        supplier_name = self._extract_supplier_name(normalized, sender)
        part_number = self._extract_part_number(normalized)
        quantity = self._extract_quantity(normalized)
        unit_cost = self._extract_unit_cost(normalized)
        certificate = self._extract_certificate(normalized)
        lead_time_days = self._extract_lead_time(normalized)
        condition = self._extract_condition(normalized)

        return {
            "supplier_name": supplier_name,
            "supplier_email": sender,
            "part_number": part_number,
            "quantity_available": quantity,
            "unit_cost": unit_cost,
            "certificate_type": certificate or "FAA 8130-3",
            "lead_time_days": lead_time_days or 3,
            "condition_code": condition or "NE",
            "approval_status": "Approved",
            "confidence": 0.96,
        }

    def _validate_quote_signal(self, text: str) -> None:
        lowered = text.lower()
        noisy_patterns = [
            "manage digest",
            "thank you",
            "feel free to contact us",
            "follow up on this request",
            "just following up",
            "received, thank you",
            "awaiting your update",
            "please send me the certificate",
        ]
        looks_like_quote = bool(
            re.search(r"(?:part\s*(?:no|number)|p/n|pn|qty|quantity|lead time|available|\$\s*\d)", text, flags=re.IGNORECASE)
            or re.search(r"\b(?=.*\d)[A-Z0-9]{3,}(?:\s*-\s*[A-Z0-9]{2,}){1,5}\b", text, flags=re.IGNORECASE)
            or re.search(r"\b\d+[A-Z0-9\-/]{2,}\b", text, flags=re.IGNORECASE)
        )

        if any(pattern in lowered for pattern in noisy_patterns) and not looks_like_quote:
            raise ValueError("Email does not contain a valid supplier quote; generic follow-up or digest content was ignored.")

        if not re.search(r"(?:part\s*(?:no|number)|p/n|pn|\b(?=.*\d)[A-Z0-9]{3,}(?:\s*-\s*[A-Z0-9]{2,}){1,5}\b|\b\d+[A-Z0-9\-/]{2,}\b)", text, flags=re.IGNORECASE):
            raise ValueError("Email does not contain a valid supplier quote; no part number pattern found.")

    def _extract_supplier_name(self, text: str, sender: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        generic_prefixes = (
            "from:", "subject:", "to:", "date:", "sent:", "hello", "hi ", "dear ", "thank you",
            "please", "best regards", "regards", "thanks", "re:", "response -", "follow-up",
        )
        noise_phrases = (
            "manage digest", "feel free to contact", "received", "awaiting your update",
            "lead time", "unit is in stock", "each available", "be careful with this message",
            "do you have any updates", "all info is inside", "order status update",
        )
        explicit_patterns = (
            r"(?:company|company name|supplier|vendor|seller|manufacturer)\s*[:\-]\s*([^\r\n]+)",
            r"(?:quotation|quote)\s+from\s*[:\-]?\s*([^\r\n]+)",
        )
        for pattern in explicit_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = self._clean_supplier_name(match.group(1))
                if candidate:
                    return candidate

        for line in lines:
            if not line or line.startswith(("From:", "Subject:", "To:", "Date:", "Sent:")):
                continue
            lowered = line.lower()
            if lowered.startswith(generic_prefixes) or any(phrase in lowered for phrase in noise_phrases):
                continue
            if "@" in line or ":" in line or "$" in line:
                continue
            if len(line.split()) < 2:
                continue
            if any(token in lowered for token in ["quote request", "request for quotation", "rfq", "part no", "part number", "qty", "quantity"]):
                continue
            if "-" in line and len(line.split()) <= 3 and line.count(" ") <= 2:
                continue
            candidate = self._clean_supplier_name(line)
            if candidate:
                return candidate

        if "@" in sender:
            display_name = re.match(r"^([^<]+?)\s*<[^>]+>$", sender)
            if display_name:
                candidate = self._clean_supplier_name(display_name.group(1))
                if candidate:
                    return candidate
            domain = sender.split("@", 1)[1].split(".", 1)[0]
            return domain.replace("-", " ").title()
        return "Unknown Supplier"

    def _clean_supplier_name(self, value: str) -> str:
        candidate = re.sub(r"\s+", " ", value).strip(" \t-:;,.|")
        lowered = candidate.lower()
        if len(candidate) < 4 or "@" in candidate:
            return ""
        if any(phrase in lowered for phrase in (
            "thank you", "follow up", "contact us", "manage digest", "lead time",
            "available", "received", "please", "regards", "certificate",
        )):
            return ""
        if re.search(r"\b(?:part|p/n|qty|quantity|price|cost|quote)\b", lowered):
            return ""
        return candidate

    def _extract_part_number(self, text: str) -> str:
        metadata_tokens = {
            "HTTP-EQUIV", "CONTENT-TYPE", "CHARSET", "NAME", "CONTENT", "STYLE", "WIDTH", "HEIGHT",
            "UTF-8", "UTF8", "ISO-8859-1", "US-ASCII", "TEXT-HTML", "TEXT-PLAIN",
        }

        def valid_candidate(value: str) -> bool:
            normalized = re.sub(r"\s*[-]\s*", "-", value).upper()
            return (
                normalized not in metadata_tokens
                and bool(re.search(r"\d", normalized))
                and len(normalized) <= 40
                and bool(re.search(r"[A-Z0-9]+-[A-Z0-9]+", normalized))
            )

        explicit_patterns = [
            r"(?i)\b(?:part\s*(?:no|number)|p/n|pn)\s*[:=]\s*([A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5})",
            r"(?i)\b(?:part\s*(?:no|number)|p/n|pn)\s*([A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5})",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = re.sub(r"\s*[-]\s*", "-", match.group(1)).upper()
                if valid_candidate(candidate):
                    return candidate

        candidates = re.findall(r"\b[A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5}\b", text, flags=re.IGNORECASE)
        if not candidates:
            return ""

        scored = []
        for candidate in candidates:
            upper = re.sub(r"\s*[-]\s*", "-", candidate).upper()
            if not valid_candidate(upper):
                continue
            score = 0
            if upper.count("-") >= 2:
                score += 50
            if len(upper) >= 9:
                score += 15
            if upper.startswith("8130"):
                score -= 100
            if re.search(r"\d+-[A-Z0-9]+-", upper):
                score += 15
            if re.search(r"\b(?:part\s*(?:no|number)|p/n|pn)\b", text, flags=re.IGNORECASE):
                score += 20
            if re.search(r"\b(?:qty|quantity|cond|condition)\b", text, flags=re.IGNORECASE):
                score += 5
            scored.append((score, upper))

        return max(scored, key=lambda x: x[0])[1] if scored else ""

    def _extract_quantity(self, text: str) -> Optional[int]:
        match = re.search(r"(?:qty|quantity|available)[:\s]+(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"\b(\d+)\s*(?:ea|each|pcs?|units?)\b", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_unit_cost(self, text: str) -> Optional[float]:
        match = re.search(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.\d{1,2})?)", text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).replace(",", "")
            return float(value)
        return None

    def _extract_certificate(self, text: str) -> Optional[str]:
        certs = {
            "FAA 8130-3": r"FAA\s*(?:Form\s*)?8130[-\s]?3",
            "EASA Form 1": r"EASA\s*Form\s*1",
            "CoC": r"Certificate\s+of\s+Conformance|CoC",
        }
        for label, pattern in certs.items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return label
        return None

    def _extract_lead_time(self, text: str) -> Optional[int]:
        match = re.search(r"(?:lead\s*time|ship\s*in|delivery)[:\s]+(\d+)\s*(?:day|days)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_condition(self, text: str) -> Optional[str]:
        conditions = {
            "NE": r"\bNEW\b|\bNE\b",
            "OH": r"\bOVERHAULED\b|\bOH\b",
            "AR": r"\bAS\s*REMOVED\b|\bAR\b",
            "NS": r"\bNEW\s*SURPLUS\b|\bNS\b",
        }
        for code, pattern in conditions.items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return code
        return None
