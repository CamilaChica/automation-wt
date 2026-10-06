"""Build dedicated training databases for client and supplier communication agents.

- client_communications_training.db: dedicated database for training the model of the agent of communications with the clients.
- supplier_communications_training.db: dedicated database for training the model of the agent of communications with the suppliers.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
COMMUNICATIONS_DATA_PATH = ROOT / "data" / "dspy" / "winged_tycoons_communications.json"
CLIENT_TRAINING_DB_PATH = ROOT / "data" / "client_communications_training.db"
SUPPLIER_TRAINING_DB_PATH = ROOT / "data" / "supplier_communications_training.db"

CANONICAL_SIGNATURE = (
    "Camila Chica\n"
    "Winged Tycoons | AOG & MRO Parts Sourcing\n"
    "Direct: +1 (786) 349-3433 | 24/7 Sourcing Desk\n"
    "Web: https://portal.wingedtycoons.com\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "✈ 24/7 AOG Support | FAA 8130-3 & EASA Form 1 Traceability\n"
    "✈ Direct Warehouse Dispatch | Outright Commercial Aviation Spares\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
)

CLIENT_SYSTEM_PROMPT = (
    "You are Camila Chica, Senior Aviation Parts Specialist at Winged Tycoons. "
    "You communicate with airlines, MRO facilities, and aerospace procurement clients. "
    "Guidelines:\n"
    "1. Always address the client contact warmly using their first name if available.\n"
    "2. State that units and pricing are verified against our current inventory/stock (NEVER mention or disclose third-party suppliers).\n"
    "3. Unit location and standard warranty can be provided; worldwide shipping is available; sales are outright only (no exchange/core returns).\n"
    "4. Always close professionally and warmly, being the last one interacting, and sign canonically as:\n"
    f"{CANONICAL_SIGNATURE}"
)

SUPPLIER_SYSTEM_PROMPT = (
    "You are Camila Chica from the Sourcing & Purchasing desk at Winged Tycoons. "
    "You communicate with aviation parts suppliers, distributors, and OEMs. "
    "Guidelines:\n"
    "1. Request quotes, availability confirmation (especially for quotes 30+ days old), documentation (FAA 8130-3, trace, CoC), and lead times.\n"
    "2. When purchase intent is indicated, conduct up to two polite rounds of commercial discount bargaining.\n"
    "3. Never disclose client identity or end-user customer details to suppliers.\n"
    "4. Always maintain a warm, human-like closing and sign canonically as:\n"
    f"{CANONICAL_SIGNATURE}"
)


def _init_client_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS database_metadata;
        DROP TABLE IF EXISTS client_training_samples;
        DROP TABLE IF EXISTS model_instruction_tuning;
        DROP TABLE IF EXISTS few_shot_demonstrations;

        CREATE TABLE database_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE client_training_samples (
            id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            direction TEXT NOT NULL,
            client_company TEXT,
            client_contact TEXT,
            client_email TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            part_number TEXT,
            condition TEXT,
            unit_price REAL,
            currency TEXT DEFAULT 'USD',
            expected_extracted_data JSON,
            expected_actions JSON,
            canonical_signature TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE model_instruction_tuning (
            id TEXT PRIMARY KEY,
            sample_id TEXT,
            task_type TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            assistant_response TEXT NOT NULL,
            quality_score REAL NOT NULL DEFAULT 1.0,
            guardrails_verified INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (sample_id) REFERENCES client_training_samples(id)
        );

        CREATE TABLE few_shot_demonstrations (
            id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            input_context TEXT NOT NULL,
            target_draft TEXT NOT NULL,
            key_rationale TEXT,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()


def _init_supplier_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS database_metadata;
        DROP TABLE IF EXISTS supplier_training_samples;
        DROP TABLE IF EXISTS model_instruction_tuning;
        DROP TABLE IF EXISTS few_shot_demonstrations;

        CREATE TABLE database_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE supplier_training_samples (
            id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            direction TEXT NOT NULL,
            supplier_company TEXT,
            supplier_contact TEXT,
            supplier_email TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            part_number TEXT,
            condition TEXT,
            unit_cost REAL,
            currency TEXT DEFAULT 'USD',
            lead_time_days INTEGER,
            certificate_type TEXT,
            expected_extracted_data JSON,
            expected_actions JSON,
            canonical_signature TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE model_instruction_tuning (
            id TEXT PRIMARY KEY,
            sample_id TEXT,
            task_type TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            assistant_response TEXT NOT NULL,
            quality_score REAL NOT NULL DEFAULT 1.0,
            guardrails_verified INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (sample_id) REFERENCES supplier_training_samples(id)
        );

        CREATE TABLE few_shot_demonstrations (
            id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            input_context TEXT NOT NULL,
            target_draft TEXT NOT NULL,
            key_rationale TEXT,
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()


def clean_body_for_client(body: str, contact_name: str | None = None) -> str:
    """Ensure client communications use personal salutation, stock wording, and canonical signature."""
    text = str(body or "").strip()
    
    # 1. Personal salutation if contact_name available
    if contact_name and "@" not in contact_name:
        first_name = contact_name.split()[0].title()
        text = re.sub(r"^(?:Dear|Hi|Hello)\s+[^\n,]+[,!]?", f"Hi {first_name},", text, count=1, flags=re.IGNORECASE)

    # 2. Supplier wording replacement -> current stock
    supplier_replacements = [
        (r"(?i)\bsecure\s+(?:the\s+)?(?:units?|parts?)\s+(?:with|from)\s+(?:our\s+|the\s+)?suppliers?\b", "secure the unit from our current stock"),
        (r"(?i)\bsecuring\s+(?:the\s+)?(?:units?|parts?)\s+(?:with|from)\s+(?:our\s+|the\s+)?suppliers?\b", "securing the unit from our current stock"),
        (r"(?i)\b(?:getting|gathering|sourcing|procuring|purchasing|acquiring)\s+(?:the\s+)?(?:units?|parts?|information)\s+(?:from|with)\s+(?:our\s+|the\s+)?suppliers?\b", "gathering the information from our current stock"),
        (r"(?i)\b(?:from|with)\s+(?:our\s+|the\s+)?suppliers?\b", "from our current stock"),
        (r"(?i)\b(?:our\s+|the\s+)?supplier(?:'s)?\s+(?:stock|inventory|network)\b", "our current stock"),
    ]
    for pat, rep in supplier_replacements:
        text = re.sub(pat, rep, text)

    # 3. Canonical signature for outbound
    if "Winged Tycoons" in text and ("Best regards" in text or "Warm regards" in text or "Kind regards" in text):
        # normalize signature
        text = re.sub(
            r"(?i)(?:Best|Warm|Kind)\s+regards,.*$",
            f"Best regards,\n\n{CANONICAL_SIGNATURE}",
            text,
            flags=re.DOTALL,
        )
    return text


def clean_body_for_supplier(body: str, supplier_contact: str | None = None) -> str:
    """Ensure supplier communications use canonical signature and clear sourcing terminology."""
    text = str(body or "").strip()
    if "Winged Tycoons" in text and ("Best regards" in text or "Warm regards" in text or "Kind regards" in text):
        text = re.sub(
            r"(?i)(?:Best|Warm|Kind)\s+regards,.*$",
            f"Best regards,\n\n{CANONICAL_SIGNATURE}",
            text,
            flags=re.DOTALL,
        )
    return text


def build_client_training_database() -> int:
    """Build and populate client_communications_training.db."""
    CLIENT_TRAINING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CLIENT_TRAINING_DB_PATH)
    _init_client_db(conn)

    with open(COMMUNICATIONS_DATA_PATH, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    client_records = corpus.get("client_communications", [])
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    sample_count = 0
    instruction_count = 0

    for rec in client_records:
        rec_id = rec.get("id")
        scenario = rec.get("scenario", "client_communication")
        direction = rec.get("direction", "inbound")
        data = rec.get("expected_extracted_data", {})
        client_name = data.get("customer_name") or data.get("customer") or ""
        client_email = rec.get("from", "") if direction == "inbound" else rec.get("to", "")
        subject = rec.get("subject", "")
        
        # Clean outbound body
        raw_body = rec.get("body", "")
        body = clean_body_for_client(raw_body, client_name) if direction == "outbound" else raw_body

        # Part details
        lines = data.get("lines") or data.get("sample_rows_parsed") or []
        first_line = lines[0] if lines else {}
        part_number = first_line.get("part_number") or data.get("part_number") or ""
        condition = first_line.get("condition") or data.get("condition") or ""
        unit_price = float(first_line.get("unit_price_usd") or first_line.get("target_price_usd") or 0.0)

        cur.execute("""
            INSERT INTO client_training_samples (
                id, scenario, direction, client_company, client_contact, client_email,
                subject, body, part_number, condition, unit_price, currency,
                expected_extracted_data, expected_actions, canonical_signature, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?)
        """, (
            rec_id, scenario, direction, client_name, client_name, client_email,
            subject, body, part_number, condition, unit_price,
            json.dumps(data), json.dumps(rec.get("expected_app_actions", {})),
            CANONICAL_SIGNATURE if direction == "outbound" else None, now
        ))
        sample_count += 1

        # Instruction tuning pair
        if direction == "outbound":
            inst_id = f"INST-CLI-{rec_id}"
            user_prompt = (
                f"Client Contact: {client_name}\n"
                f"Client Email: {client_email}\n"
                f"Scenario: {scenario}\n"
                f"Part Number: {part_number}\n"
                f"Condition: {condition}\n"
                f"Target / Quoted Price: ${unit_price:,.2f} USD\n"
                f"Context / Subject: {subject}\n\n"
                "Please draft the official client response email following Winged Tycoons operational policies."
            )
            cur.execute("""
                INSERT INTO model_instruction_tuning (
                    id, sample_id, task_type, system_prompt, user_prompt,
                    assistant_response, quality_score, guardrails_verified, created_at
                ) VALUES (?, ?, 'client_email_draft', ?, ?, ?, 1.0, 1, ?)
            """, (
                inst_id, rec_id, CLIENT_SYSTEM_PROMPT, user_prompt, body, now
            ))
            instruction_count += 1

        # Few shot demonstrations for key scenarios
        if scenario in {"quote_to_client", "alternate_offer", "missing_info_request_to_client"} and direction == "outbound":
            demo_id = f"DEMO-CLI-{rec_id}"
            input_context = f"Requirement: {part_number} ({condition}), Client: {client_name}"
            cur.execute("""
                INSERT OR IGNORE INTO few_shot_demonstrations (
                    id, scenario, input_context, target_draft, key_rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                demo_id, scenario, input_context, body,
                "Demonstrates personalized salutation, stock-sourced narrative, clear pricing, and canonical signature.", now
            ))

    # Add specific policy instruction tuning entries:
    # 1. Worldwide shipping inquiry
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'client_policy_qa', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-CLI-POLICY-SHIPPING",
        CLIENT_SYSTEM_PROMPT,
        "Client Question: 'Do you deliver internationally or provide worldwide shipping options?'\nReference Quote: QTE-WW-01\nCustomer: Delta MRO Services",
        "Hi Delta MRO Team,\n\n"
        "Thank you for reaching out! Yes, we provide fast international and worldwide shipping/dispatch options to support global operations. "
        "We coordinate airfreight, courier priority, and hazardous-material transport as required.\n\n"
        "Please let us know your preferred destination airport or facility address and we will provide exact transit details.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    # 2. Outright vs Exchange policy
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'client_policy_qa', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-CLI-POLICY-EXCHANGE",
        CLIENT_SYSTEM_PROMPT,
        "Client Question: 'Can we purchase this unit on an exchange or core-return basis?'\nReference Quote: QTE-EX-01\nCustomer: Aero Maintenance LLC",
        "Hi Aero Maintenance Team,\n\n"
        "Thank you for contacting us regarding quotation QTE-EX-01. "
        "Please note that we sell this unit on an outright purchase basis only (no core exchange or return required). "
        "This allows immediate dispatch without core deposit holds or core condition evaluations.\n\n"
        "Please reply directly to this thread with your PO to lock in this outright unit.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    # 3. Unit location disclosure
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'client_policy_qa', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-CLI-POLICY-LOCATION",
        CLIENT_SYSTEM_PROMPT,
        "Client Question: 'Where is this unit physically located?'\nReference Quote: QTE-LOC-01\nCustomer: JetTech Aerospace",
        "Hi JetTech Team,\n\n"
        "Thank you for inquiring about quotation QTE-LOC-01. "
        "The unit is physically located in our United States warehouse (Florida facility) and is available for immediate inspection, packaging, and dispatch.\n\n"
        "Please let us know if you need freight forwarder pick-up coordinates or shipping rates.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    # 4. 30-minute chase follow-up
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'client_quote_chase', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-CLI-CHASE-30MIN",
        CLIENT_SYSTEM_PROMPT,
        "Task: Chase client 30 minutes after quote dispatch.\nReference Quote: QTE-99214\nPart Number: 31050-001\nCustomer: Alpha Aero Maintenance",
        "Hi Alpha Aero Team,\n\n"
        "Following up on Quotation QTE-99214 for Part Number 31050-001 sent a short while ago.\n\n"
        "As aviation stock is subject to prior sale, please let us know if you would like to proceed with your Purchase Order (PO) "
        "or if you have any questions regarding pricing, lead time, or airworthiness documentation.\n\n"
        "We are ready to secure this unit for you immediately upon your authorization.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('database_name', 'client_communications_training', ?)", (now,))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('target_agent', 'CustomerCommunicationAgent', ?)", (now,))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('total_samples', ?, ?)", (str(sample_count), now))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('total_instruction_pairs', ?, ?)", (str(instruction_count + 4), now))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('canonical_signature', ?, ?)", (CANONICAL_SIGNATURE, now))

    conn.commit()
    conn.close()
    return sample_count


def build_supplier_training_database() -> int:
    """Build and populate supplier_communications_training.db."""
    SUPPLIER_TRAINING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SUPPLIER_TRAINING_DB_PATH)
    _init_supplier_db(conn)

    with open(COMMUNICATIONS_DATA_PATH, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    supplier_records = corpus.get("supplier_communications", [])
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    sample_count = 0
    instruction_count = 0

    for rec in supplier_records:
        rec_id = rec.get("id")
        scenario = rec.get("scenario", "supplier_communication")
        direction = rec.get("direction", "inbound")
        data = rec.get("expected_extracted_data", {})
        supplier_name = data.get("supplier") or ""
        supplier_email = rec.get("from", "") if direction == "inbound" else rec.get("to", "")
        subject = rec.get("subject", "")

        raw_body = rec.get("body", "")
        body = clean_body_for_supplier(raw_body, supplier_name) if direction == "outbound" else raw_body

        lines = data.get("lines") or data.get("sample_rows_parsed") or []
        first_line = lines[0] if lines else {}
        part_number = first_line.get("part_number") or data.get("part_number") or ""
        condition = first_line.get("condition") or data.get("condition") or ""
        unit_cost = float(first_line.get("unit_cost_usd") or first_line.get("unit_price_usd") or 0.0)
        lead_time = int(first_line.get("lead_time_days") or 3)
        cert = first_line.get("certification") or first_line.get("cert") or ""

        cur.execute("""
            INSERT INTO supplier_training_samples (
                id, scenario, direction, supplier_company, supplier_contact, supplier_email,
                subject, body, part_number, condition, unit_cost, currency, lead_time_days, certificate_type,
                expected_extracted_data, expected_actions, canonical_signature, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?)
        """, (
            rec_id, scenario, direction, supplier_name, supplier_name, supplier_email,
            subject, body, part_number, condition, unit_cost, lead_time, cert,
            json.dumps(data), json.dumps(rec.get("expected_app_actions", {})),
            CANONICAL_SIGNATURE if direction == "outbound" else None, now
        ))
        sample_count += 1

        if direction == "outbound":
            inst_id = f"INST-SUP-{rec_id}"
            user_prompt = (
                f"Supplier: {supplier_name}\n"
                f"Supplier Email: {supplier_email}\n"
                f"Scenario: {scenario}\n"
                f"Part Number: {part_number}\n"
                f"Condition: {condition}\n"
                f"Quoted Cost: ${unit_cost:,.2f} USD\n"
                f"Context / Subject: {subject}\n\n"
                "Please draft the official supplier outreach email following Winged Tycoons purchasing policies."
            )
            cur.execute("""
                INSERT INTO model_instruction_tuning (
                    id, sample_id, task_type, system_prompt, user_prompt,
                    assistant_response, quality_score, guardrails_verified, created_at
                ) VALUES (?, ?, 'supplier_email_draft', ?, ?, ?, 1.0, 1, ?)
            """, (
                inst_id, rec_id, SUPPLIER_SYSTEM_PROMPT, user_prompt, body, now
            ))
            instruction_count += 1

        if scenario in {"availability_check", "discount_request", "documentation_request", "request_missing_information", "purchase_order_to_supplier"} and direction == "outbound":
            demo_id = f"DEMO-SUP-{rec_id}"
            input_context = f"Requirement: {part_number} ({condition}), Supplier: {supplier_name}"
            cur.execute("""
                INSERT OR IGNORE INTO few_shot_demonstrations (
                    id, scenario, input_context, target_draft, key_rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                demo_id, scenario, input_context, body,
                "Demonstrates precise purchasing inquiry, required tag verification, and canonical signature.", now
            ))

    # Add specific supplier policy instruction tuning entries:
    # 1. 30-Day Stale Offer Reconfirmation
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'supplier_stale_confirmation', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-SUP-STALE-CONFIRM",
        SUPPLIER_SYSTEM_PROMPT,
        "Task: Reconfirm quotation older than 30 days.\nPart Number: 65-52803-32\nSupplier: Precision Aero Parts\nPrevious Quote Date: 45 days ago\nQuantity: 1 EA",
        "Hello Precision Aero Parts Team,\n\n"
        "We are reviewing your previous quotation for part 65-52803-32 (quantity 1 EA). "
        "As our client has submitted an active RFQ for this requirement, please confirm in this same email thread "
        "whether the quoted material is still available and whether the price, condition, certification, lead time, and quote validity remain current.\n\n"
        "If any detail has changed, please provide the updated terms and attach the applicable trace documentation.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    # 2. 2-Round Discount Bargaining - Round 1
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'supplier_discount_round_1', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-SUP-DISCOUNT-R1",
        SUPPLIER_SYSTEM_PROMPT,
        "Task: Bargain for commercial discount upon customer purchase intent (Round 1).\nPart Number: 31050-001\nSupplier: SkyHigh Components LLC\nInitial Quoted Cost: $3,200.00 USD\nTarget Discount: 5%",
        "Dear SkyHigh Components Team,\n\n"
        "Thank you for providing the quotation for PN 31050-001 at $3,200.00 USD.\n\n"
        "Our customer is ready to proceed with a purchase order. Could you please confirm whether you can offer a 5% commercial discount, "
        "bringing the unit price to $3,040.00 USD? This will allow us to lock in the order immediately on your behalf.\n\n"
        "We appreciate your partnership and look forward to finalizing this purchase.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    # 3. 2-Round Discount Bargaining - Round 2 (Final Counteroffer)
    cur.execute("""
        INSERT INTO model_instruction_tuning (
            id, sample_id, task_type, system_prompt, user_prompt, assistant_response, quality_score, guardrails_verified, created_at
        ) VALUES (?, NULL, 'supplier_discount_round_2', ?, ?, ?, 1.0, 1, ?)
    """, (
        "INST-SUP-DISCOUNT-R2",
        SUPPLIER_SYSTEM_PROMPT,
        "Task: Second and final round of commercial discount bargaining.\nPart Number: 31050-001\nSupplier: SkyHigh Components LLC\nSupplier Counter: $3,150.00 USD\nFinal Target: $3,080.00 USD",
        "Dear SkyHigh Components Team,\n\n"
        "Thank you for reviewing our commercial request and offering $3,150.00 USD.\n\n"
        "To finalize this order right now with our buyer, can we meet at $3,080.00 USD as our final target? "
        "Upon your confirmation, we will issue our formal purchase order and payment coordinates.\n\n"
        "Thank you for your continued support.\n\n"
        f"Best regards,\n\n{CANONICAL_SIGNATURE}",
        now,
    ))

    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('database_name', 'supplier_communications_training', ?)", (now,))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('target_agent', 'SupplierDiscoveryAgent / PurchasingDesk', ?)", (now,))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('total_samples', ?, ?)", (str(sample_count), now))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('total_instruction_pairs', ?, ?)", (str(instruction_count + 3), now))
    cur.execute("INSERT INTO database_metadata (key, value, updated_at) VALUES ('canonical_signature', ?, ?)", (CANONICAL_SIGNATURE, now))

    conn.commit()
    conn.close()
    return sample_count


def build_both_training_databases():
    print("=" * 60)
    print("Building Dedicated Agent Training Databases")
    print("=" * 60)
    
    cli_count = build_client_training_database()
    print(f"[OK] Client Communications Training Database created: {CLIENT_TRAINING_DB_PATH}")
    print(f"     Loaded {cli_count} client samples with instruction tuning & few-shot tables.")

    sup_count = build_supplier_training_database()
    print(f"[OK] Supplier Communications Training Database created: {SUPPLIER_TRAINING_DB_PATH}")
    print(f"     Loaded {sup_count} supplier samples with instruction tuning & few-shot tables.")
    print("=" * 60)


if __name__ == "__main__":
    build_both_training_databases()
