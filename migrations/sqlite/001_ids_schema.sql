BEGIN;

CREATE TABLE IF NOT EXISTS series (
  series_code INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  owner_dept TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category (
  cat_code CHAR(3) PRIMARY KEY,
  series_code INTEGER NOT NULL,
  name TEXT NOT NULL,
  part_type TEXT NOT NULL DEFAULT 'material',
  FOREIGN KEY (series_code) REFERENCES series(series_code) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS vendor (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_alias (
  alias TEXT PRIMARY KEY,
  vendor_id INTEGER NOT NULL,
  FOREIGN KEY (vendor_id) REFERENCES vendor(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS part (
  pn CHAR(12) PRIMARY KEY,
  cat_code CHAR(3) NOT NULL,
  item INTEGER NOT NULL,
  dash INTEGER NOT NULL,
  rev TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  description TEXT,
  drawing TEXT,
  vendor_id INTEGER,
  creator TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  attrs TEXT DEFAULT '{}',
  base_key TEXT,
  ownership TEXT,
  customer_id TEXT,
  rma_no TEXT,
  linked_pn CHAR(12),
  detail_prefix TEXT,
  detail_suffix TEXT,
  detail_code TEXT,
  rule_version TEXT,
  idempotency_key TEXT,
  note TEXT,
  source TEXT NOT NULL DEFAULT 'api',
  FOREIGN KEY (cat_code) REFERENCES category(cat_code) ON UPDATE CASCADE,
  FOREIGN KEY (vendor_id) REFERENCES vendor(id) ON DELETE SET NULL,
  FOREIGN KEY (linked_pn) REFERENCES part(pn) ON DELETE SET NULL,
  CONSTRAINT uq_cat_item_dash UNIQUE (cat_code, item, dash),
  CONSTRAINT ck_pn_format CHECK (
    length(pn) = 12
    AND substr(pn, 4, 1) = '-'
    AND substr(pn, 9, 1) = '-'
    AND substr(pn, 1, 3) GLOB '[0-9][0-9][0-9]'
    AND substr(pn, 5, 4) GLOB '[0-9][0-9][0-9][0-9]'
    AND substr(pn, 10, 2) GLOB '[0-9][0-9]'
  ),
  CONSTRAINT ck_cat_matches_pn CHECK (substr(pn, 1, 3) = cat_code),
  CONSTRAINT ck_item_bounds CHECK (item BETWEEN 0 AND 9999),
  CONSTRAINT ck_dash_bounds CHECK (dash BETWEEN 0 AND 99)
);

CREATE TABLE IF NOT EXISTS part_history (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  pn CHAR(12) NOT NULL,
  rev TEXT,
  change_note TEXT,
  state TEXT,
  changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  changed_by TEXT,
  FOREIGN KEY (pn) REFERENCES part(pn) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reserved_numbers (
  cat_code CHAR(3) NOT NULL,
  item INTEGER NOT NULL,
  dash INTEGER,
  reason TEXT,
  reserved_by TEXT,
  reserved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (cat_code, item, dash)
);

CREATE TABLE IF NOT EXISTS counters (
  cat_code CHAR(3) PRIMARY KEY,
  next_item INTEGER NOT NULL CHECK (next_item >= 0),
  FOREIGN KEY (cat_code) REFERENCES category(cat_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS detail_counters (
  cat_code CHAR(3) NOT NULL,
  detail_prefix TEXT NOT NULL,
  next_suffix INTEGER NOT NULL CHECK (next_suffix >= 0),
  PRIMARY KEY (cat_code, detail_prefix),
  FOREIGN KEY (cat_code) REFERENCES category(cat_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sample_state (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  pn CHAR(12) NOT NULL,
  state TEXT NOT NULL,
  note TEXT,
  at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  by_user TEXT,
  FOREIGN KEY (pn) REFERENCES part(pn) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_part_cat_item ON part(cat_code, item);
CREATE INDEX IF NOT EXISTS idx_part_status ON part(status);
CREATE INDEX IF NOT EXISTS idx_part_base_key ON part(base_key);
CREATE INDEX IF NOT EXISTS idx_part_attrs ON part(attrs);
CREATE UNIQUE INDEX IF NOT EXISTS uq_part_idempotency ON part(idempotency_key) WHERE idempotency_key IS NOT NULL;

INSERT OR REPLACE INTO series(series_code, name, owner_dept) VALUES
  (000, 'Admin/Docs', 'Admin'),
  (200, 'Production Material', 'Purchasing'),
  (300, 'LCD/STN', 'Purchasing'),
  (400, 'Electronics/Touch/PCB', 'Purchasing'),
  (500, 'Controllers/Drivers/Brackets', 'Purchasing'),
  (600, 'Film/Glass', 'Purchasing'),
  (700, 'Value Add (Tools/Assy/Bond)', 'Engineering/ADT'),
  (800, 'CSM (Customer Supplied)', 'Engineering/ADT'),
  (900, 'Engineering & RMA', 'Engineering/ADT'),
  (975, 'Engineering Sample', 'Engineering/ADT'),
  (980, 'Engineering Sample (Alt)', 'Engineering/ADT');

COMMIT;
