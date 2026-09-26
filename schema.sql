PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    email TEXT NOT NULL,
    phone TEXT,
    country TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    email TEXT NOT NULL,
    phone TEXT,
    country TEXT,
    preferred INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parts (
    id TEXT PRIMARY KEY,
    part_number TEXT NOT NULL UNIQUE,
    description TEXT,
    manufacturer TEXT,
    category TEXT,
    condition TEXT,
    certification TEXT,
    quantity_available INTEGER NOT NULL DEFAULT 0,
    unit_cost REAL,
    selling_price REAL,
    currency TEXT NOT NULL DEFAULT 'USD',
    lead_time INTEGER,
    location TEXT,
    supplier_id TEXT REFERENCES suppliers(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rfqs (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    part_number TEXT,
    description TEXT,
    quantity INTEGER NOT NULL,
    condition_requested TEXT,
    certification_requested TEXT,
    required_date TEXT,
    destination TEXT,
    status TEXT NOT NULL,
    raw_text TEXT,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_quotes (
    id TEXT PRIMARY KEY,
    rfq_id TEXT NOT NULL REFERENCES rfqs(id),
    supplier_id TEXT REFERENCES suppliers(id),
    part_number TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    condition TEXT,
    certification TEXT,
    availability INTEGER,
    lead_time INTEGER,
    quote_expiration TEXT,
    discount_requested REAL,
    discount_received REAL,
    final_supplier_price REAL,
    supplier_reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_quotes (
    id TEXT PRIMARY KEY,
    rfq_id TEXT NOT NULL REFERENCES rfqs(id),
    quote_number TEXT NOT NULL UNIQUE,
    unit_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    total_price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    lead_time INTEGER,
    condition TEXT,
    certification TEXT,
    valid_until TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_quote_items (
    id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL REFERENCES customer_quotes(id),
    rfq_item_id TEXT,
    part_number TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL,
    condition TEXT,
    certification TEXT,
    unit_price REAL NOT NULL,
    lead_time INTEGER,
    attachments TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    quote_id TEXT REFERENCES customer_quotes(id),
    po_number TEXT NOT NULL UNIQUE,
    po_date TEXT,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS communications (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    sender TEXT NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT,
    message TEXT,
    message_type TEXT,
    status TEXT NOT NULL,
    sent_at TEXT,
    response_received TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_events (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    execution_time TEXT,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_review_queue (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    task TEXT NOT NULL,
    prompt_version TEXT,
    entity_id TEXT,
    source_text TEXT NOT NULL,
    extraction_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    hold_flags_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'PENDING',
    decision TEXT,
    decision_by TEXT,
    decision_payload TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_telemetry (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_calls_json TEXT NOT NULL DEFAULT '[]',
    latency_ms REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    validation_result TEXT NOT NULL,
    operator_review_outcome TEXT,
    review_queue_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations_state (
    state_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS carrier_webhook_events (
    event_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rfqs_status ON rfqs(status);
CREATE INDEX IF NOT EXISTS idx_supplier_quotes_rfq ON supplier_quotes(rfq_id);
CREATE INDEX IF NOT EXISTS idx_customer_quotes_rfq ON customer_quotes(rfq_id);
CREATE INDEX IF NOT EXISTS idx_customer_quote_items_quote ON customer_quote_items(quote_id);
CREATE INDEX IF NOT EXISTS idx_communications_entity ON communications(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_automation_events_entity ON automation_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_automation_events_status ON automation_events(status, created_at);
CREATE INDEX IF NOT EXISTS idx_operator_review_status ON operator_review_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_operator_review_entity ON operator_review_queue(entity_id);
CREATE INDEX IF NOT EXISTS idx_llm_telemetry_task_created ON llm_telemetry(task, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_telemetry_review ON llm_telemetry(review_queue_id);
