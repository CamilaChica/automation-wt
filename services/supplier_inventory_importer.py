"""Import recognized supplier inventory tables into normalized offers and row audit."""

from __future__ import annotations

import hashlib
import uuid
from email.utils import parseaddr
from typing import Any

from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.supplier_inventory_parser import normalize_inventory_row, parse_supplier_inventory_attachment
from services.communication_service import communication_service


def _save_offer(**offer: Any) -> Any:
    if operations_store.storage_engine == "postgresql":
        return operations_store.save_supplier_offer(**offer)
    return supplier_db.save_supplier_offer(**offer)


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

    sender_header = str(message.get("from") or "")
    sender_name, sender_email = parseaddr(sender_header)
    sender_email = sender_email or sender_header if "@" in sender_header else sender_email
    supplier_name = sender_name or (sender_email.rsplit("@", 1)[-1] if "@" in sender_email else "Unknown Supplier")
    source_message_id = str(message.get("internet_message_id") or message.get("message_id") or f"inventory-{uuid.uuid4().hex}")
    summaries = []
    imported_part_numbers: set[str] = set()

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
            for part_number, missing_fields in sorted(followups.items()):
                result = communication_service.request_missing_supplier_fields(
                    recipient=sender_email,
                    part_number=part_number,
                    missing_fields=sorted(missing_fields),
                    reply_to=reply_to,
                )
                followup_results.append({"part_number": part_number, **result})
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