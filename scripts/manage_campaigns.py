"""Command-line tool to manage, inspect, and trigger email campaigns."""

import argparse
import json
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.email_campaign_service import (
    CAMPAIGN_CLIENTS,
    CAMPAIGN_SUPPLIERS,
    CAMPAIGN_USER_FEEDBACK,
    email_campaign_service,
)


def print_status():
    summaries = email_campaign_service.get_campaign_summaries()
    print("=" * 80)
    print("WINGED TYCOONS - EMAIL CAMPAIGN STATUS")
    print("=" * 80)
    for c in summaries:
        print(f"\nCampaign: {c['name']} (ID: {c['id']})")
        print(f"  Target Audience: {c['target_audience']}")
        print(f"  Status:          {c['status']}")
        print(f"  Schedule Type:   {c['schedule_type']}")
        print(f"  Scheduled Start: {c['scheduled_start_at']}")
        print(f"  From Mailbox:    {c['from_mailbox']}")
        print(f"  Subject:         {c['subject']}")
        print(f"  Template:        {c['template_path']}")
        m = c["metrics"]
        print(f"  Metrics:         Total: {m['total']} | Sent: {m['sent']} | Pending: {m['pending']} | Scheduled: {m['scheduled']} | Failed: {m['failed']}")
    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Winged Tycoons Email Campaign Manager")
    parser.add_argument("--status", action="store_true", help="Display status of all 3 campaigns")
    parser.add_argument("--prepare", action="store_true", help="Prepare dispatches for suppliers and clients")
    parser.add_argument("--run-suppliers", action="store_true", help="Execute immediate supplier campaign")
    parser.add_argument("--process-due", action="store_true", help="Process due dispatches across all campaigns")
    parser.add_argument("--campaign", type=str, choices=["suppliers", "clients", "feedback"], help="Target specific campaign")
    parser.add_argument("--schedule-feedback", type=str, metavar="EMAIL", help="Schedule 1-hour feedback email for a user")
    parser.add_argument("--name", type=str, default="", help="Contact name for user feedback")
    parser.add_argument("--company", type=str, default="", help="Company name for user feedback")

    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        print_status()
        return

    if args.prepare:
        print("Preparing Supplier Campaign (1 per unique domain)...")
        sup = email_campaign_service.prepare_supplier_campaign()
        print("Supplier campaign:", json.dumps(sup, indent=2))

        print("\nPreparing Client Campaign (Scheduled for next week)...")
        cli = email_campaign_service.prepare_client_campaign()
        print("Client campaign:", json.dumps(cli, indent=2))

    if args.run_suppliers:
        print("Executing Supplier Campaign (Effective Immediately)...")
        res = email_campaign_service.run_supplier_campaign_now()
        print("Result:", json.dumps(res, indent=2))

    if args.schedule_feedback:
        print(f"Scheduling 1-hour feedback email for: {args.schedule_feedback}...")
        res = email_campaign_service.schedule_user_feedback(
            user_email=args.schedule_feedback,
            first_name=args.name,
            company_name=args.company,
        )
        print("Feedback schedule result:", json.dumps(res, indent=2))

    if args.process_due:
        target_id = None
        if args.campaign == "suppliers":
            target_id = CAMPAIGN_SUPPLIERS
        elif args.campaign == "clients":
            target_id = CAMPAIGN_CLIENTS
        elif args.campaign == "feedback":
            target_id = CAMPAIGN_USER_FEEDBACK

        print("Processing due dispatches...")
        res = email_campaign_service.process_due_dispatches(campaign_id=target_id)
        print("Processing result:", json.dumps(res, indent=2))

    if args.status or args.prepare or args.run_suppliers or args.process_due:
        print_status()


if __name__ == "__main__":
    main()
