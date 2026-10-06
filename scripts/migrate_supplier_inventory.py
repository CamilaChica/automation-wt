import sqlite3
import os

for db_file in ['data/supplier_email_store.db', r'C:\var\data\supplier_email_store.db']:
    if os.path.exists(db_file):
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("UPDATE supplier_parts SET part_number = '456-789', condition_code = 'OH', description = 'Actuator Assembly (A320)' WHERE part_number = '456-789-OH'")
        c.execute("UPDATE supplier_parts SET description = 'Actuator Assembly (A320)' WHERE part_number = '456-789' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET unit_cost = 20.00, description = 'Washer, Flat (Aircraft Hardware)' WHERE part_number = 'AN960-416' AND (unit_cost < 1.0 OR unit_cost IS NULL)")
        c.execute("UPDATE supplier_parts SET description = 'Washer, Flat (Aircraft Hardware)' WHERE part_number = 'AN960-416'")
        c.execute("UPDATE supplier_parts SET description = 'Weather Radar Receiver-Transmitter (B737)' WHERE part_number = '060-1234-00' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET description = 'Solid Universal Head Rivet' WHERE part_number = 'MS20470AD4-6' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET description = 'Self-Locking Hex Nut' WHERE part_number = 'MS21042-3' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET description = 'Brake Assembly Unit' WHERE part_number LIKE 'BRK-3200%' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET description = 'Mechanical Actuator Unit' WHERE part_number LIKE 'ACT-7788%' AND (description IS NULL OR description = '')")
        c.execute("UPDATE supplier_parts SET description = 'Regulated Defense Component' WHERE part_number LIKE 'ITAR-9000%' AND (description IS NULL OR description = '')")
        conn.commit()
        conn.close()
        print(f"Migrated {db_file}")

# Verify
for db_file in ['data/supplier_email_store.db', r'C:\var\data\supplier_email_store.db']:
    if os.path.exists(db_file):
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT part_number, unit_cost, condition_code, description FROM supplier_parts").fetchall()
        print(f"=== {db_file} ===")
        for r in rows:
            print(dict(r))
        conn.close()
