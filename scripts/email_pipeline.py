"""Bounded supplier and sales mailbox pipeline runs.

Outbound follow-ups and customer replies are dry-run unless --send-live and
--confirm-live-dispatch are both supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.communication_service import communication_service
from services.db_service import db_service
from services.mailbox_service import fetch_inbox_messages
from services.orchestration_service import orchestration_service
from services.supplier_database import supplier_db
from services.supplier_email_loader import SupplierEmailLoader


def _parse_window(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([hd])", value.strip().lower())
    if not match:
        raise ValueError("Window must use hours or days, for example 24h or 1d.")
    amount, unit = int(match.group(1)), match.group(2)
    return timedelta(hours=amount if unit == "h" else amount * 24)


def _received_at(message: dict[str, Any]) -> datetime:
    value = message.get("date") or message.get("receivedDateTime")
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _missing_supplier_fields(email_text: str, result: dict[str, Any]) -> list[str]:
    missing = []
    if not result.get("unit_cost"):
        missing.append("price and currency")
    if not result.get("condition_code"):
        missing.append("condition code")
    if not re.search(r"warranty|guarantee|months?\s+warranty|years?\s+warranty", email_text, re.IGNORECASE):
        missing.append("warranty period or terms")
    if not result.get("certificate_type") and not re.search(r"8130|easa|certificate|coc|trace", email_text, re.IGNORECASE):
        missing.append("trace documents such as FAA 8130-3, EASA Form 1, or CoC")
    if not result.get("quantity_available"):
        missing.append("available quantity")
    if not result.get("lead_time_days"):
        missing.append("lead time")
    return missing


def _send_or_preview(action: dict[str, Any], send_live: bool, confirm_live_dispatch: bool) -> dict[str, Any]:
    if not send_live or not confirm_live_dispatch:
        action["transmission_status"] = "DRY_RUN"
        return action
    result = communication_service._send(
        "purchasing",
        action["recipient"],
        action["subject"],
        action["body"],
        reply_to=action.get("reply_to"),
    )
    action["transmission_status"] = result["transmission_status"]
    action["communication_id"] = result.get("communication_id")
    return action


def run_purchasing(args: argparse.Namespace) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - _parse_window(args.window)
    messages = fetch_inbox_messages("purchasing", limit=args.limit)
    loader = SupplierEmailLoader()
    processed = []
    followups = []
    for message in messages:
        if _received_at(message) < cutoff:
            continue
        message_id = str(message.get("message_id") or "")
        if message_id and supplier_db.is_email_processed("purchasing", message_id):
            continue
        body = str(message.get("body") or "")
        email_text = f"From: {message.get('from', '')}\nSubject: {message.get('subject', '')}\n\n{body}"
        result = loader.load_raw_email_text(email_text, mailbox="purchasing", message_id=message_id or None)
        record = {"message_id": message_id, "sender": message.get("from", ""), "subject": message.get("subject", ""), "result": result}
        processed.append(record)
        if result.get("success"):
            missing = _missing_supplier_fields(email_text, result)
            record["missing_fields"] = missing
            if missing and "@" in str(message.get("from", "")):
                action = {
                    "recipient": message["from"],
                    "subject": f"Re: Quote request {result.get('part_number', '')} - information required",
                    "body": "Hello,\n\nThank you for your quotation. To complete our records, please provide:\n\n" + "\n".join(f"- {field}" for field in missing) + "\n\nKind regards,\nWinged Tycoons Purchasing Team",
                    "reply_to": message_id or None,
                    "part_number": result.get("part_number"),
                    "missing_fields": missing,
                }
                followups.append(_send_or_preview(action, args.send_live, args.confirm_live_dispatch))
    return {"mailbox": "purchasing", "window": args.window, "processed": processed, "followups": followups}


def run_sales(args: argparse.Namespace) -> dict[str, Any]:
    messages = fetch_inbox_messages("sales", limit=args.limit)
    results = []
    for message in messages:
        message_id = str(message.get("message_id") or "")
        if message_id and supplier_db.is_email_processed("sales", message_id):
            continue
        sender = str(message.get("from") or "")
        body = str(message.get("body") or "").strip()
        if "@" not in sender or not body:
            continue
        rfq = db_service.create_rfq(
            customer_name=sender.split("@", 1)[0].replace(".", " ").title(),
            customer_email=sender,
            raw_text=f"From: {sender}\nSubject: {message.get('subject', '')}\n\n{body}",
            thread_id=message_id or None,
        )
        pipeline_result = asyncio.run(orchestration_service.process_rfq_pipeline(rfq.id))
        if message_id:
            supplier_db.save_email("sales", message_id, sender, str(message.get("subject") or ""), body)
        results.append({"message_id": message_id, "sender": sender, "rfq_id": rfq.id, "pipeline": pipeline_result})
    return {"mailbox": "sales", "processed": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Winged Tycoons email pipelines.")
    parser.add_argument("--mailbox", choices=("purchasing", "sales"), required=True)
    parser.add_argument("--action", choices=("ingest_and_audit", "test_reply_rfqs"), required=True)
    parser.add_argument("--window", default="24h")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--send-live", action="store_true")
    parser.add_argument("--confirm-live-dispatch", action="store_true")
    args = parser.parse_args()
    if args.mailbox == "purchasing" and args.action != "ingest_and_audit":
        parser.error("purchasing requires --action ingest_and_audit")
    if args.mailbox == "sales" and args.action != "test_reply_rfqs":
        parser.error("sales requires --action test_reply_rfqs")
    result = run_purchasing(args) if args.mailbox == "purchasing" else run_sales(args)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
