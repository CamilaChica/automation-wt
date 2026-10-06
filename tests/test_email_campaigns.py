import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.email_campaign_service import (
    CAMPAIGN_CLIENTS,
    CAMPAIGN_SUPPLIERS,
    CAMPAIGN_USER_FEEDBACK,
    EmailCampaignService,
    extract_domain,
    extract_first_name,
    get_next_week_start,
)


class TestEmailCampaignService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_ops_db = os.path.join(self.temp_dir.name, "test_campaign_ops.db")
        self.test_sup_db = os.path.join(self.temp_dir.name, "test_campaign_sup.db")

        # Seed test suppliers with duplicate domains
        sconn = sqlite3.connect(self.test_sup_db)
        sconn.execute(
            """CREATE TABLE suppliers (
                id TEXT PRIMARY KEY,
                company_name TEXT,
                email TEXT
            )"""
        )
        sconn.executemany(
            "INSERT INTO suppliers VALUES (?, ?, ?)",
            [
                ("S1", "Apex Aero One", "quotes@apexaero.com"),
                ("S2", "Apex Aero Alternate", "sales@apexaero.com"),  # Same domain!
                ("S3", "Apex Aero Third", "procurement@apexaero.com"), # Same domain!
                ("S4", "Delta Spares", "info@deltaspares.com"),
                ("S5", "Horizon MRO", "sales@horizonmro.com"),
            ],
        )
        sconn.commit()
        sconn.close()

        # Seed test clients
        oconn = sqlite3.connect(self.test_ops_db)
        oconn.execute(
            """CREATE TABLE client_quote_history (
                id TEXT PRIMARY KEY,
                client_email TEXT,
                client_name TEXT,
                company_name TEXT
            )"""
        )
        oconn.executemany(
            "INSERT INTO client_quote_history VALUES (?, ?, ?, ?)",
            [
                ("Q1", "buyer@americanair.com", "Robert Smith", "American Airlines"),
                ("Q2", "buyer@americanair.com", "Robert Smith", "American Airlines"), # Duplicate quote
                ("Q3", "purchasing@lufthansa-mro.de", "Helga Schmidt", "Lufthansa Technik"),
            ],
        )
        oconn.commit()
        oconn.close()

        self.service = EmailCampaignService(db_path=self.test_ops_db, supplier_db_path=self.test_sup_db)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_supplier_campaign_deduplicates_domain_and_retains_fallbacks(self):
        result = self.service.prepare_supplier_campaign()
        self.assertEqual(result["campaign_id"], CAMPAIGN_SUPPLIERS)
        self.assertEqual(result["unique_domains"], 3)  # apexaero.com, deltaspares.com, horizonmro.com
        self.assertEqual(result["dispatches_created"], 3)

        with self.service._connect_ops() as conn:
            dispatches = conn.execute(
                "SELECT recipient_email, domain, fallback_contacts FROM email_campaign_dispatches WHERE campaign_id = ?",
                (CAMPAIGN_SUPPLIERS,),
            ).fetchall()

            apex_disp = next(d for d in dispatches if d["domain"] == "apexaero.com")
            self.assertEqual(apex_disp["recipient_email"], "quotes@apexaero.com")
            # Fallbacks must contain the other emails for that domain
            self.assertIn("sales@apexaero.com", apex_disp["fallback_contacts"])
            self.assertIn("procurement@apexaero.com", apex_disp["fallback_contacts"])

    def test_supplier_campaign_fallback_on_delivery_failure(self):
        self.service.prepare_supplier_campaign()

        with self.service._connect_ops() as conn:
            apex_disp = conn.execute(
                "SELECT id FROM email_campaign_dispatches WHERE campaign_id = ? AND domain = 'apexaero.com'",
                (CAMPAIGN_SUPPLIERS,),
            ).fetchone()
            dispatch_id = apex_disp["id"]

        # Simulate delivery failure on primary email
        with patch("services.email_campaign_service.send_message", side_effect=RuntimeError("Mailbox unavailable")):
            sent = self.service.send_dispatch(dispatch_id)
            self.assertFalse(sent)

        # Verify fallback contact is queued as pending for the same domain
        with self.service._connect_ops() as conn:
            failed_disp = conn.execute("SELECT status, error_message FROM email_campaign_dispatches WHERE id = ?", (dispatch_id,)).fetchone()
            self.assertEqual(failed_disp["status"], "FAILED")

            fallback_disp = conn.execute(
                "SELECT id, recipient_email, status FROM email_campaign_dispatches WHERE id = 'disp-sup-apexaero_com-fallback'",
            ).fetchone()
            self.assertIsNotNone(fallback_disp)
            self.assertEqual(fallback_disp["recipient_email"], "sales@apexaero.com")
            self.assertEqual(fallback_disp["status"], "PENDING")

    def test_client_campaign_scheduled_for_next_week(self):
        next_week_target = get_next_week_start()
        result = self.service.prepare_client_campaign(scheduled_start=next_week_target)
        self.assertEqual(result["campaign_id"], CAMPAIGN_CLIENTS)
        self.assertEqual(result["total_clients"], 2)  # buyer@americanair.com, purchasing@lufthansa-mro.de
        self.assertEqual(result["dispatches_created"], 2)

        with self.service._connect_ops() as conn:
            dispatches = conn.execute(
                "SELECT recipient_email, status, scheduled_for FROM email_campaign_dispatches WHERE campaign_id = ?",
                (CAMPAIGN_CLIENTS,),
            ).fetchall()
            for d in dispatches:
                self.assertEqual(d["status"], "SCHEDULED")
                self.assertEqual(d["scheduled_for"], next_week_target.isoformat())

    def test_user_feedback_campaign_scheduled_one_hour_after_login_first_time_only(self):
        now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
        user_email = "new.airline.buyer@united.com"

        # First login schedules the email 1 hour later
        sched1 = self.service.schedule_user_feedback(user_email, first_name="Michael", company_name="United Airlines", now=now)
        self.assertTrue(sched1["scheduled"])
        self.assertEqual(sched1["recipient_email"], user_email)
        expected_scheduled_for = (now + timedelta(hours=1)).isoformat()
        self.assertEqual(sched1["scheduled_for"], expected_scheduled_for)

        # Second login attempts should NOT duplicate the schedule (First time only)
        sched2 = self.service.schedule_user_feedback(user_email, first_name="Michael", company_name="United Airlines", now=now + timedelta(minutes=10))
        self.assertFalse(sched2["scheduled"])
        self.assertEqual(sched2["reason"], "already_scheduled_or_sent")

        # Verify only 1 dispatch was created
        with self.service._connect_ops() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM email_campaign_dispatches WHERE campaign_id = ? AND recipient_email = ?",
                (CAMPAIGN_USER_FEEDBACK, user_email),
            ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_template_rendering_replaces_tags(self):
        html_suppliers = self.service.render_template(
            self.service.get_campaign_summaries()[0]["template_path"],
            first_name="Alexander",
            company_name="Apex Aero Components",
            recipient_email="quotes@apexaero.com",
        )
        self.assertIn("Hello Alexander,", html_suppliers)
        self.assertIn("welcome Apex Aero Components", html_suppliers)
        self.assertNotIn("{{first_name}}", html_suppliers)
        self.assertNotIn("{{company_name}}", html_suppliers)
        self.assertNotIn("{{unsubscribe_url}}", html_suppliers)

    def test_extract_helpers(self):
        self.assertEqual(extract_domain("User.Name@Aero-Parts.Co.Uk"), "aero-parts.co.uk")
        self.assertEqual(extract_first_name("Carlos Santana"), "Carlos")
        self.assertEqual(extract_first_name("", "claudia.garcia@delta.com"), "Claudia")


if __name__ == "__main__":
    unittest.main()
