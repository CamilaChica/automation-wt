"""Tests for dedicated client and supplier communication agent training databases."""

import json
import os
import unittest
from pathlib import Path

from services.training_databases import TrainingDatabaseService, CLIENT_TRAINING_DB_PATH, SUPPLIER_TRAINING_DB_PATH


class TestTrainingDatabases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = TrainingDatabaseService()

    def test_client_training_database_exists_and_populated(self):
        self.assertTrue(CLIENT_TRAINING_DB_PATH.exists(), "Client training database must exist.")
        summary = self.service.get_database_summary("client")
        self.assertEqual(summary["database_type"], "client")
        self.assertGreaterEqual(summary["sample_count"], 200)
        self.assertGreaterEqual(summary["instruction_tuning_count"], 50)
        self.assertGreaterEqual(summary["few_shot_demonstration_count"], 1)

    def test_supplier_training_database_exists_and_populated(self):
        self.assertTrue(SUPPLIER_TRAINING_DB_PATH.exists(), "Supplier training database must exist.")
        summary = self.service.get_database_summary("supplier")
        self.assertEqual(summary["database_type"], "supplier")
        self.assertGreaterEqual(summary["sample_count"], 200)
        self.assertGreaterEqual(summary["instruction_tuning_count"], 50)
        self.assertGreaterEqual(summary["few_shot_demonstration_count"], 1)

    def test_client_training_samples_enforce_no_supplier_disclosure(self):
        samples = self.service.list_training_samples("client", limit=200, direction="outbound")
        for sample in samples:
            body = sample["body"].lower()
            # Must not state getting/sourcing parts from our supplier
            self.assertNotRegex(body, r"\b(?:from|with)\s+(?:our\s+|the\s+)?suppliers?\b")
            self.assertNotRegex(body, r"\b(?:our\s+|the\s+)?supplier(?:'s)?\s+(?:stock|inventory|network)\b")
            # If signature is present, it must be the canonical signature
            if "winged tycoons" in body:
                self.assertIn("camila chica", body)
                self.assertIn("349-3433", body)

    def test_client_policy_instruction_pairs(self):
        dataset = self.service.get_instruction_tuning_dataset("client", task_type="client_policy_qa")
        tasks = {row["id"]: row for row in dataset}
        
        # 1. Worldwide shipping
        self.assertIn("INST-CLI-POLICY-SHIPPING", tasks)
        shipping_resp = tasks["INST-CLI-POLICY-SHIPPING"]["assistant_response"]
        self.assertIn("worldwide shipping", shipping_resp.lower())
        self.assertIn("camila chica", shipping_resp.lower())

        # 2. Outright only (no exchange)
        self.assertIn("INST-CLI-POLICY-EXCHANGE", tasks)
        exchange_resp = tasks["INST-CLI-POLICY-EXCHANGE"]["assistant_response"]
        self.assertIn("outright purchase basis only", exchange_resp.lower())
        self.assertIn("no core exchange", exchange_resp.lower())

        # 3. Location
        self.assertIn("INST-CLI-POLICY-LOCATION", tasks)
        loc_resp = tasks["INST-CLI-POLICY-LOCATION"]["assistant_response"]
        self.assertIn("warehouse", loc_resp.lower())

    def test_client_30_min_chase_instruction_pair(self):
        dataset = self.service.get_instruction_tuning_dataset("client", task_type="client_quote_chase")
        self.assertGreaterEqual(len(dataset), 1)
        chase_resp = dataset[0]["assistant_response"]
        self.assertIn("following up on quotation", chase_resp.lower())
        self.assertIn("camila chica", chase_resp.lower())

    def test_supplier_stale_and_bargaining_instruction_pairs(self):
        # 1. 30-day stale reconfirmation
        stale_dataset = self.service.get_instruction_tuning_dataset("supplier", task_type="supplier_stale_confirmation")
        self.assertGreaterEqual(len(stale_dataset), 1)
        stale_resp = stale_dataset[0]["assistant_response"]
        self.assertIn("reviewing your previous quotation", stale_resp.lower())
        self.assertIn("still available", stale_resp.lower())
        self.assertIn("camila chica", stale_resp.lower())

        # 2. Two-round discount bargaining
        r1_dataset = self.service.get_instruction_tuning_dataset("supplier", task_type="supplier_discount_round_1")
        self.assertGreaterEqual(len(r1_dataset), 1)
        r1_resp = r1_dataset[0]["assistant_response"]
        self.assertIn("commercial discount", r1_resp.lower())

        r2_dataset = self.service.get_instruction_tuning_dataset("supplier", task_type="supplier_discount_round_2")
        self.assertGreaterEqual(len(r2_dataset), 1)
        r2_resp = r2_dataset[0]["assistant_response"]
        self.assertIn("final target", r2_resp.lower())

    def test_export_openai_jsonl(self):
        tmp_client = Path("scratch/test_client_tuning.jsonl")
        count = self.service.export_openai_jsonl("client", tmp_client)
        self.assertGreaterEqual(count, 50)
        self.assertTrue(tmp_client.exists())
        with open(tmp_client, "r", encoding="utf-8") as f:
            first_line = json.loads(f.readline())
            self.assertIn("messages", first_line)
            self.assertEqual(len(first_line["messages"]), 3)
            self.assertEqual(first_line["messages"][0]["role"], "system")
            self.assertEqual(first_line["messages"][1]["role"], "user")
            self.assertEqual(first_line["messages"][2]["role"], "assistant")
        if tmp_client.exists():
            tmp_client.unlink()


if __name__ == "__main__":
    unittest.main()
