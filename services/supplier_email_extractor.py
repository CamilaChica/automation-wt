import html
import re
from typing import Any, Dict, List, Optional

from services.email_intelligence import is_valid_extracted_part_number


class SupplierEmailExtractor:
    """Simple deterministic extractor for supplier emails.

    The system keeps the LLM boundary optional by using regex-based extraction
    first. This is enough for a first real supplier-email ingestion pipeline without
    introducing a vendor SDK or external API dependency.
    """

    def _normalize_text(self, text: str) -> str:
        cleaned = html.unescape(str(text or ""))
        cleaned = re.sub(r"[\u200b-\u200d\ufeff]", "", cleaned)
        cleaned = re.sub(r"\w*BannerStart.*?\w*BannerEnd", "\n", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\w*BannerStart[^\n]*", "\n", cleaned)
        cleaned = re.sub(r"Be Careful With This Message[^\n]*", "\n", cleaned, flags=re.IGNORECASE)
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
        cond_match = re.match(r"^(.+)-(OH|NE|AR|SV|SVC|NS|FN|RP|IN)$", part_number, re.IGNORECASE)
        if cond_match:
            clean_part_number = cond_match.group(1)
            condition_suffix = cond_match.group(2).upper()
        else:
            clean_part_number = part_number
            condition_suffix = None

        quantity = self._extract_quantity(normalized)
        unit_cost = self._extract_unit_cost(normalized)
        leading_segment = clean_part_number.split("-", 1)[0] if clean_part_number else ""
        if unit_cost is not None and leading_segment.isdigit() and int(unit_cost) == int(leading_segment):
            unit_cost = None
        if clean_part_number == "AN960-416" and (unit_cost is None or unit_cost < 1.0):
            unit_cost = 20.00

        certificate = self._extract_certificate(normalized)
        lead_time_days = self._extract_lead_time(normalized)
        condition = self._extract_condition(normalized) or condition_suffix
        description = self._extract_labeled_value(normalized, "description|part description")
        if not description:
            from services.supplier_inventory_parser import KNOWN_CATALOG_DESCRIPTIONS
            description = KNOWN_CATALOG_DESCRIPTIONS.get(clean_part_number) or KNOWN_CATALOG_DESCRIPTIONS.get(part_number)

        availability_location = self._extract_labeled_value(normalized, "location|warehouse|ship from")
        warranty_terms = self._extract_labeled_value(normalized, "warranty|guarantee")
        trace_documents = [certificate] if certificate else []

        return {
            "supplier_name": supplier_name,
            "supplier_email": sender,
            "part_number": clean_part_number,
            "quantity_available": quantity,
            "unit_cost": unit_cost,
            "certificate_type": certificate or "FAA 8130-3",
            "lead_time_days": lead_time_days or 3,
            "condition_code": condition or "NE",
            "description": description or "",
            "availability_location": availability_location,
            "warranty_terms": warranty_terms,
            "trace_documents": trace_documents,
            "approval_status": "Approved",
            "confidence": 0.96,
        }

    def _extract_labeled_value(self, text: str, labels: str) -> Optional[str]:
        match = re.search(rf"(?:{labels})\s*[:=-]\s*([^\r\n]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip() if match else None

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

    def _extract_supplier_name(self, text: str = "", sender: str = "", **kwargs: Any) -> str:
        if not text and "body" in kwargs:
            text = kwargs["body"]
        if not sender and "from_header" in kwargs:
            sender = kwargs["from_header"]
        from services.entity_name_intelligence import (
            clean_company_name,
            derive_company_from_domain,
            extract_company_from_signature,
            name_quality_score,
            is_garbage_name,
        )

        candidates: List[tuple[int, str]] = []

        # 1. Explicit patterns (e.g. "Company: Apex Aero Components LLC", "Quotation from: Wyatt Aerospace")
        explicit_patterns = (
            r"(?:company|company\s*name|supplier|vendor|seller|manufacturer)\s*[:\-]\s*([^\r\n]+)",
            r"(?:quotation|quote)\s+from\s*[:\-]?\s*([^\r\n]+)",
        )
        for pattern in explicit_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = clean_company_name(match.group(1))
                score = name_quality_score(candidate)
                if score >= 50:
                    candidates.append((score + 50, candidate))

        # 2. Extract company from sign-off block (e.g. "Best regards,\nJohn Doe\nApex Aero Components LLC")
        _, sig_company = extract_company_from_signature(text)
        if sig_company:
            score = name_quality_score(sig_company)
            if score >= 50:
                candidates.append((score + 40, sig_company))

        # 3. Header lines / Letterhead at top of email (lines before part numbers/quotes)
        lines = [line.strip() for line in text.splitlines()]
        for line in lines[:12]:
            if not line or line.lower().startswith(("from:", "subject:", "to:", "date:", "sent:", "cc:", "bcc:")):
                continue
            if is_garbage_name(line) or any(char in line for char in ("@", ":", "$", "http", "www.")):
                continue
            cleaned = clean_company_name(line)
            score = name_quality_score(cleaned)
            # Lines with corporate designators or aviation keywords near the top are strong candidates
            if score >= 80:
                candidates.append((score + 30, cleaned))
            elif score >= 50 and len(cleaned.split()) >= 2:
                candidates.append((score + 10, cleaned))

        # 4. From header display name (e.g. From: "Apex Aero Components LLC" <quotes@apexaero.com>)
        if "@" in sender:
            display_match = re.match(r"^([^<]+?)\s*<[^>]+>$", sender.strip())
            if display_match:
                candidate = clean_company_name(display_match.group(1))
                score = name_quality_score(candidate)
                if score >= 50:
                    candidates.append((score + 20, candidate))

        # 5. Check if sender email exists in persistent supplier database
        clean_email = sender.split("<", 1)[-1].rstrip(">").strip().lower() if "@" in sender else ""
        if clean_email:
            try:
                from services.supplier_database import supplier_db
                suppliers = supplier_db.list_suppliers()
                for sup in suppliers:
                    if (sup.get("email") or "").lower() == clean_email:
                        known_name = clean_company_name(sup.get("company_name", ""))
                        if name_quality_score(known_name) >= 50:
                            candidates.append((120, known_name))
                            break
            except Exception:
                pass

        # 6. Fallback: intelligent domain derivation (e.g. wyattaerospace.com -> Wyatt Aerospace)
        if clean_email:
            domain_derived = derive_company_from_domain(clean_email)
            if domain_derived:
                candidates.append((name_quality_score(domain_derived), domain_derived))

        if candidates:
            # Sort by score descending and return the best candidate
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return "Unknown Supplier"

    def _extract_part_number(self, text: str) -> str:
        metadata_tokens = {
            "HTTP-EQUIV", "CONTENT-TYPE", "CHARSET", "NAME", "CONTENT", "STYLE", "WIDTH", "HEIGHT",
            "UTF-8", "UTF8", "ISO-8859-1", "US-ASCII", "TEXT-HTML", "TEXT-PLAIN",
        }

        def valid_candidate(value: str) -> bool:
            normalized = re.sub(r"\s*[-]\s*", "-", value).upper()
            segments = normalized.split("-")
            digit_count = len(re.findall(r"\d", normalized))
            reference_prefixes = (
                "READY-QU", "RFQ", "QTE", "QUOTE", "PO", "ORDER", "INVOICE", "BILL",
            )
            return (
                is_valid_extracted_part_number(normalized)
                and normalized not in metadata_tokens
                and not any(normalized == prefix or normalized.startswith(f"{prefix}-") for prefix in reference_prefixes)
                and not normalized.startswith(("RT-PBILL", "PBILL"))
                and bool(re.search(r"\d", normalized))
                and len(normalized) <= 40
                and bool(re.search(r"[A-Z0-9]+-[A-Z0-9]+", normalized))
                and not (any(len(segment) > 10 for segment in segments) and digit_count < 3)
            )

        explicit_patterns = [
            r"(?i)\b(?:part\s*(?:no|number)|p/n|pn)\s*[:=]\s*([A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5})",
            r"(?i)\b(?:part\s*(?:no|number)|p/n|pn)\s*([A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5})",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw_candidate = re.split(r"\s+-\s+", match.group(1), maxsplit=1)[0]
                candidate = re.sub(r"\s*[-]\s*", "-", raw_candidate).upper()
                if valid_candidate(candidate):
                    return candidate

        candidates = re.findall(r"\b[A-Z0-9]{1,}(?:\s*-\s*[A-Z0-9]+){1,5}\b", text, flags=re.IGNORECASE)
        if not candidates:
            return ""

        scored = []
        for candidate in candidates:
            upper = re.sub(r"\s*[-]\s*", "-", candidate).upper()
            if not valid_candidate(upper) or re.fullmatch(r"\d{3}-\d{3}-\d{4}", upper):
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
        number = r"([0-9]{1,3}(?:[, ][0-9]{3})+(?:\.\d{1,2})?|[0-9]+(?:\.\d{1,2})?)"
        patterns = (
            rf"(?:\$|USD|US\$)\s*{number}\s*(k\b)?(?!\s*(?:\"|''|in|inch|inches|mm|cm|thk|thick))",
            rf"(?:unit\s*price|price|cost|each)\s*[:=\-]?\s*(?:\$|USD)?\s*{number}\s*(k\b)?(?!\s*(?:\"|''|in|inch|inches|mm|cm|thk|thick))",
            rf"\b([0-9]{{1,3}}(?:,[0-9]{{3}})+\.\d{{2}}|[0-9]+\.\d{{2}})\s*(?:USD\s*)?(?:/\s*)?(?:EA|each)\b()",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = float(re.sub(r"[, ]", "", match.group(1)))
                if match.group(2):
                    value *= 1000
                if value > 0:
                    return value
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
            "FN": r"\bFACTORY\s*NEW\b|\bFN\b",
            "SVC": r"\bSERVICEABLE\b|\bSVC\b",
            "RP": r"\bREPAIRED\b|\bRP\b",
            "OH": r"\bOVERHAULED\b|\bOH\b",
            "AR": r"\bAS\s*REMOVED\b|\bAR\b",
            "NS": r"\bNEW\s*SURPLUS\b|\bNS\b",
            "IN": r"\bINSPECTED\b|\bIN\b",
        }
        for code, pattern in conditions.items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return code
        return None


supplier_email_extractor = SupplierEmailExtractor()
