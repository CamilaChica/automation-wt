PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    account_status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    raw_part_number TEXT NOT NULL,
    clean_part_number TEXT NOT NULL,
    description TEXT,
    condition TEXT NOT NULL,
    quantity_available INTEGER NOT NULL CHECK (quantity_available >= 0),
    unit_cost_usd REAL NOT NULL CHECK (unit_cost_usd >= 0),
    location TEXT,
    lead_time_days INTEGER CHECK (lead_time_days >= 0),
    source_email_id TEXT,
    last_updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT,
    UNIQUE (supplier_id, clean_part_number, condition)
);

CREATE TABLE IF NOT EXISTS client_rfqs (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    inventory_item_id TEXT,
    clean_part_number TEXT NOT NULL,
    requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING_QUOTE', 'QUOTED', 'PO_PENDING', 'SOLVED', 'CANCELLED')
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
    FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    client_rfq_id TEXT NOT NULL,
    supplier_id TEXT NOT NULL,
    po_status TEXT NOT NULL CHECK (
        po_status IN ('PENDING_PROCUREMENT', 'ISSUED_TO_VENDOR', 'SHIPPED', 'COMPLETED')
    ),
    total_amount_usd REAL NOT NULL CHECK (total_amount_usd >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_rfq_id) REFERENCES client_rfqs(id) ON DELETE CASCADE,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS purchasing_email_ingestion (
    source_email_id TEXT PRIMARY KEY,
    supplier_email TEXT NOT NULL,
    inventory_item_id TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_clean_part
    ON inventory_items(clean_part_number);

CREATE INDEX IF NOT EXISTS idx_client_rfqs_client_status
    ON client_rfqs(client_id, status);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_status
    ON purchase_orders(po_status);
