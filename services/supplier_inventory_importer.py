"""Import recognized supplier inventory tables into normalized offers and row audit."""

from __future__ import annotations

import hashlib
import re
import uuid
from email.utils import parseaddr
from typing import Any

from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.supplier_inventory_parser import normalize_inventory_row, parse_supplier_inventory_attachment
from services.communication_service import communication_service
from services.inbound_email_archive import _received_at


def _consolidate_followups(followups: dict[str, set[str]]) -> tuple[str, list[str]]:
    """One email per supplier: list all parts in the subject and the union of missing fields."""
    parts = sorted(followups)
    label = ", ".join(parts[:5]) + (f" (+{len(parts) - 5} more)" if len(parts) > 5 else "")
    fields = sorted({field for missing in followups.values() for field in missing})
    return label, fields


def has_inventory_table_attachments(message: dict[str, Any]) -> bool:
    for attachment in message.get("attachments") or []:
        content = attachment.get("content") or b""
        if not isinstance(content, bytes):
            continue
        if parse_supplier_inventory_attachment(
            str(attachment.get("filename") or "attachment"),
            str(attachment.get("content_type") or "application/octet-stream"),
            content,
        ):
            return True
    return False


def _save_offer(**offer: Any) -> Any:
    if operations_store.storage_engine == "postgresql":
        return operations_store.save_supplier_offer(**offer)
    return supplier_db.save_supplier_offer(**offer)


def _resolve_supplier_identity(message: dict[str, Any], parsed_files: list) -> tuple[str, str]:
    from services.entity_name_intelligence import (
        clean_company_name,
        derive_company_from_domain,
        extract_company_from_signature,
        name_quality_score,
    )
    sender_header = str(message.get("from") or "").strip()
    sender_name, sender_email = parseaddr(sender_header)
    sender_email = (sender_email or (sender_header if "@" in sender_header else "")).strip("<> ").lower()

    candidates: list[tuple[int, str]] = []

    # 1. From header display name if it represents a company
    if sender_name:
        cleaned = clean_company_name(sender_name)
        score = name_quality_score(cleaned)
        if score >= 50:
            candidates.append((score + 40, cleaned))

    # 2. Check existing persistent supplier DB
    if sender_email:
        try:
            suppliers = supplier_db.list_suppliers()
            for sup in suppliers:
                if (sup.get("email") or "").lower() == sender_email:
                    known_name = clean_company_name(sup.get("company_name", ""))
                    if name_quality_score(known_name) >= 50:
                        candidates.append((120, known_name))
                        break
        except Exception:
            pass

    # 3. Signature block in message body
    body = str(message.get("body") or "")
    if body:
        _, sig_company = extract_company_from_signature(body)
        if sig_company:
            score = name_quality_score(sig_company)
            if score >= 50:
                candidates.append((score + 30, sig_company))

    # 4. Email Subject line
    subject = str(message.get("subject") or "")
    if subject:
        subj_clean = re.sub(r"(?i)\b(?:inventory|feed|stock|list|availab\w*|parts|catalog|update|sheet)\b", " ", subject)
        cleaned_subj = clean_company_name(subj_clean)
        score = name_quality_score(cleaned_subj)
        if score >= 50:
            candidates.append((score + 20, cleaned_subj))

    # 5. Attachment filenames
    for attachment, _, _ in parsed_files:
        fn = str(attachment.get("filename") or "")
        fn_clean = re.sub(r"\.[a-zA-Z0-9]+$", "", fn).replace("_", " ").replace("-", " ")
        fn_clean = re.sub(r"(?i)\b(?:inventory|feed|stock|list|availab\w*|parts|catalog|update|sheet|\d{4,})\b", " ", fn_clean)
        cleaned_fn = clean_company_name(fn_clean)
        score = name_quality_score(cleaned_fn)
        if score >= 50:
            candidates.append((score + 15, cleaned_fn))

    # 6. Domain derivation
    if sender_email:
        derived = derive_company_from_domain(sender_email)
        if derived:
            candidates.append((name_quality_score(derived), derived))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], sender_email

    fallback = sender_name or (derive_company_from_domain(sender_email) if sender_email else "Unknown Supplier")
    return fallback, sender_email


def import_inventory_attachments(message: dict[str, Any], mailbox: str) -> dict[str, Any] | None:
    """Import spreadsheet/PDF tables; return None when no attachment table is recognized."""
    attachments = message.get("attachments") or []
    parsed_files = []
    for attachment in attachments:
        filename = str(attachment.get("filename") or "attachment")
        content = attachment.get("content") or b""
        if not isinstance(content, bytes):
            continue
        blocks = parse_supplier_inventory_attachment(
            filename, str(attachment.get("content_type") or "application/octet-stream"), content,
        )
        if blocks:
            parsed_files.append((attachment, content, blocks))
    if not parsed_files:
        return None

    supplier_name, sender_email = _resolve_supplier_identity(message, parsed_files)
    source_message_id = str(message.get("internet_message_id") or message.get("message_id") or f"inventory-{uuid.uuid4().hex}")
    summaries = []
    imported_part_numbers: set[str] = set()
    imported_items: list[dict[str, Any]] = []

    for attachment, content, blocks in parsed_files:
        filename = str(attachment.get("filename") or "attachment")
        digest = hashlib.sha256(content).hexdigest()
        if operations_store.inventory_import_exists(source_message_id, digest):
            summaries.append({"filename": filename, "skipped": True, "reason": "duplicate attachment"})
            continue

        normalized_rows: list[dict[str, Any]] = []
        imported = rejected = 0
        header_maps: dict[str, Any] = {}
        parser_names = set()
        followups: dict[str, set[str]] = {}
        for block in blocks:
            block_name = str(block.get("sheet_name") or "table")
            header_maps[block_name] = block.get("header_map") or {}
            parser_names.add(str(block.get("parser") or "table"))
            for row in block.get("rows") or []:
                normalized, error = normalize_inventory_row(row)
                missing_supplier_fields = [
                    label for field, label in (
                        ("unit_price", "unit price and currency"),
                        ("lead_time_days", "lead time"),
                        ("certificate_type", "release certificate and trace documentation"),
                    )
                    if normalized.get(field) in (None, "")
                ]
                if not error and missing_supplier_fields:
                    error = "Supplier follow-up required: " + ", ".join(missing_supplier_fields)
                    part_number = str(normalized.get("part_number") or "").strip().upper()
                    if part_number:
                        followups.setdefault(part_number, set()).update(missing_supplier_fields)
                row_number = len(normalized_rows) + 1
                normalized["source_row_number"] = normalized.get("row_number")
                normalized.update({
                    "id": f"SIR-{uuid.uuid4().hex[:24].upper()}",
                    "row_number": row_number,
                    "status": "needs_supplier_followup" if error and error.startswith("Supplier follow-up required:") else "rejected" if error else "imported",
                    "error": error,
                })
                if not error:
                    try:
                        _save_offer(
                            supplier_name=supplier_name,
                            supplier_email=sender_email or None,
                            part_number=normalized["part_number"],
                            quantity_available=normalized["quantity_available"],
                            unit_cost=normalized.get("unit_price"),
                            currency=normalized.get("currency") or "USD",
                            certificate_type=normalized.get("certificate_type"),
                            lead_time_days=normalized.get("lead_time_days"),
                            condition_code=normalized.get("condition_code"),
                            source_email_id=f"{source_message_id}:{digest[:12]}:{row_number}",
                            confidence=1.0,
                            description=normalized.get("description") or "",
                            availability_location=normalized.get("availability_location"),
                            trace_documents=[normalized["certificate_type"]] if normalized.get("certificate_type") else [],
                            source_received_at=_received_at(message.get("date")),
                        )
                        imported_part_numbers.add(normalized["part_number"])
                        imported += 1
                    except Exception as exc:
                        normalized["status"] = "rejected"
                        normalized["error"] = f"Inventory upsert failed: {type(exc).__name__}"
                        rejected += 1
                else:
                    rejected += 1
                normalized_rows.append(normalized)

        import_status = "imported" if imported and not rejected else "partial" if imported else "awaiting_supplier_data" if followups else "rejected"
        import_id = operations_store.record_inventory_import(
            mailbox=mailbox,
            source_message_id=source_message_id,
            sender=sender_email or None,
            filename=filename,
            content_sha256=digest,
            parser=",".join(sorted(parser_names)),
            sheet_name=next(iter(header_maps), None),
            header_map=header_maps,
            rows_total=len(normalized_rows),
            rows_imported=imported,
            rows_rejected=rejected,
            rejected_rows=[{"row_number": row["row_number"], "error": row["error"], "raw_values": row.get("raw_values")} for row in normalized_rows if row["status"] != "imported"],
            status=import_status,
        )
        operations_store.record_inventory_rows(import_id, normalized_rows)
        followup_results = []
        if sender_email and followups:
            reply_to = str(message.get("message_id") or message.get("internet_message_id") or "").strip() or None
            part_label, all_missing = _consolidate_followups(followups)
            result = communication_service.request_missing_supplier_fields(
                recipient=sender_email,
                part_number=part_label,
                missing_fields=all_missing,
                reply_to=reply_to,
            )
            followup_results.append({"part_number": part_label, "part_numbers": sorted(followups), **result})
        summaries.append({
            "filename": filename,
            "import_id": import_id,
            "rows_total": len(normalized_rows),
            "rows_imported": imported,
            "rows_rejected": rejected,
            "status": import_status,
            "supplier_followups": followup_results,
        })

    return {
        "success": True,
        "status": "Inventory_Table_Imported" if imported_part_numbers else "Inventory_Followup_Requested" if any(summary.get("supplier_followups") for summary in summaries) else "Inventory_Table_Rejected",
        "source_email_id": source_message_id,
        "part_numbers": sorted(imported_part_numbers),
        "imports": summaries,
    }


async def import_inventory_attachments_async(
    message: dict[str, Any], mailbox: str, repositories
) -> dict[str, Any] | None:
    """Import recognized tables through the request-scoped PostgreSQL repositories."""
    parsed_files = []
    for attachment in message.get("attachments") or []:
        filename = str(attachment.get("filename") or "attachment")
        content = attachment.get("content") or b""
        if not isinstance(content, bytes):
            continue
        blocks = parse_supplier_inventory_attachment(
            filename,
            str(attachment.get("content_type") or "application/octet-stream"),
            content,
        )
        if blocks:
            parsed_files.append((attachment, content, blocks))
    if not parsed_files:
        return None

    supplier_name, sender_email = _resolve_supplier_identity(message, parsed_files)
    source_message_id = str(
        message.get("internet_message_id")
        or message.get("message_id")
        or f"inventory-{uuid.uuid4().hex}"
    )
    summaries = []
    imported_part_numbers: set[str] = set()
    imported_items: list[dict[str, Any]] = []

    for attachment, content, blocks in parsed_files:
        filename = str(attachment.get("filename") or "attachment")
        digest = hashlib.sha256(content).hexdigest()
        if await repositories.inventory.import_for_source(source_message_id, digest):
            summaries.append({"filename": filename, "skipped": True, "reason": "duplicate attachment"})
            continue

        normalized_rows = []
        imported = rejected = 0
        header_maps = {}
        parser_names = set()
        followups: dict[str, set[str]] = {}
        for block in blocks:
            block_name = str(block.get("sheet_name") or "table")
            header_maps[block_name] = block.get("header_map") or {}
            parser_names.add(str(block.get("parser") or "table"))
            for row in block.get("rows") or []:
                normalized, error = normalize_inventory_row(row)
                missing_fields = [
                    label for field, label in (
                        ("unit_price", "unit price and currency"),
                        ("lead_time_days", "lead time"),
                        ("certificate_type", "release certificate and trace documentation"),
                    )
                    if normalized.get(field) in (None, "")
                ]
                if not error and missing_fields:
                    error = "Supplier follow-up required: " + ", ".join(missing_fields)
                    part_number = str(normalized.get("part_number") or "").strip().upper()
                    if part_number:
                        followups.setdefault(part_number, set()).update(missing_fields)
                row_number = len(normalized_rows) + 1
                normalized["source_row_number"] = normalized.get("row_number")
                normalized.update({
                    "id": f"SIR-{uuid.uuid4().hex[:24].upper()}",
                    "row_number": row_number,
                    "status": (
                        "needs_supplier_followup"
                        if error and error.startswith("Supplier follow-up required:")
                        else "rejected" if error else "imported"
                    ),
                    "error": error,
                })
                if not error:
                    try:
                        async with repositories.supplier.session.begin_nested():
                            await repositories.supplier.save_inventory_offer(
                                supplier_name=supplier_name,
                                supplier_email=sender_email or None,
                                part_number=normalized["part_number"],
                                quantity_available=normalized["quantity_available"],
                                unit_cost=normalized.get("unit_price"),
                                currency=normalized.get("currency") or "USD",
                                certificate_type=normalized.get("certificate_type"),
                                lead_time_days=normalized.get("lead_time_days"),
                                condition_code=normalized.get("condition_code"),
                                source_email_id=f"{source_message_id}:{digest[:12]}:{row_number}",
                                confidence=1.0,
                                description=normalized.get("description") or "",
                                availability_location=normalized.get("availability_location"),
                                trace_documents=(
                                    [normalized["certificate_type"]]
                                    if normalized.get("certificate_type") else []
                                ),
                                source_received_at=_received_at(message.get("date")),
                            )
                        imported_part_numbers.add(normalized["part_number"])
                        imported_items.append({
                            "part_number": normalized["part_number"],
                            "quantity_available": normalized["quantity_available"],
                            "unit_cost": normalized.get("unit_price"),
                            "source_email_id": f"{source_message_id}:{digest[:12]}:{row_number}",
                        })
                        imported += 1
                    except Exception as exc:
                        normalized["status"] = "rejected"
                        normalized["error"] = f"Inventory upsert failed: {type(exc).__name__}"
                        rejected += 1
                else:
                    rejected += 1
                normalized_rows.append(normalized)

        import_status = (
            "imported" if imported and not rejected
            else "partial" if imported
            else "awaiting_supplier_data" if followups
            else "rejected"
        )
        import_record = await repositories.inventory.create_import(
            id=f"INV-{uuid.uuid4().hex[:20].upper()}",
            mailbox=mailbox,
            source_message_id=source_message_id,
            sender=sender_email or None,
            filename=filename,
            content_sha256=digest,
            parser=",".join(sorted(parser_names)),
            sheet_name=next(iter(header_maps), None),
            header_map=header_maps,
            rows_total=len(normalized_rows),
            rows_imported=imported,
            rows_rejected=rejected,
            rejected_rows=[
                {"row_number": row["row_number"], "error": row["error"], "raw_values": row.get("raw_values")}
                for row in normalized_rows if row["status"] != "imported"
            ],
            status=import_status,
        )
        await repositories.inventory.add_rows([{
            "id": row["id"],
            "import_id": import_record.id,
            "row_number": row["row_number"],
            "part_number": row.get("part_number"),
            "description": row.get("description"),
            "quantity_available": row.get("quantity_available"),
            "condition_code": row.get("condition_code"),
            "unit_price": row.get("unit_price"),
            "currency": row.get("currency"),
            "lead_time_days": row.get("lead_time_days"),
            "certificate_type": row.get("certificate_type"),
            "availability_location": row.get("availability_location"),
            "raw_values": row.get("raw_values") or {},
            "status": row["status"],
            "error": row.get("error"),
        } for row in normalized_rows])

        followup_results = []
        if sender_email and followups:
            reply_to = str(message.get("message_id") or message.get("internet_message_id") or "").strip() or None
            part_label, all_missing = _consolidate_followups(followups)
            result = await communication_service.request_missing_supplier_fields_async(
                repositories,
                recipient=sender_email,
                part_number=part_label,
                missing_fields=all_missing,
                reply_to=reply_to,
                entity_id=import_record.id,
            )
            followup_results.append({"part_number": part_label, "part_numbers": sorted(followups), **result})
        summaries.append({
            "filename": filename,
            "import_id": import_record.id,
            "rows_total": len(normalized_rows),
            "rows_imported": imported,
            "rows_rejected": rejected,
            "status": import_status,
            "supplier_followups": followup_results,
        })

    return {
        "success": True,
        "status": "Inventory_Table_Imported" if imported_part_numbers else "Inventory_Followup_Requested" if any(summary.get("supplier_followups") for summary in summaries) else "Inventory_Table_Rejected",
        "source_email_id": source_message_id,
        "supplier_name": supplier_name,
        "supplier_email": sender_email,
        "part_numbers": sorted(imported_part_numbers),
        "items": imported_items,
        "imports": summaries,
    }