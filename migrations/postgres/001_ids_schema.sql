BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS series (
  series_code INT PRIMARY KEY,
  name TEXT NOT NULL,
  owner_dept TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category (
  cat_code CHAR(3) PRIMARY KEY,
  series_code INT NOT NULL REFERENCES series(series_code) ON UPDATE CASCADE ON DELETE RESTRICT,
  name TEXT NOT NULL,
  part_type TEXT NOT NULL DEFAULT 'material'
);

CREATE TABLE IF NOT EXISTS vendor (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_alias (
  alias TEXT PRIMARY KEY,
  vendor_id INT NOT NULL REFERENCES vendor(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS part (
  pn CHAR(12) PRIMARY KEY,
  cat_code CHAR(3) NOT NULL REFERENCES category(cat_code) ON UPDATE CASCADE,
  item INT NOT NULL,
  dash INT NOT NULL,
  rev TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  description TEXT,
  drawing TEXT,
  vendor_id INT REFERENCES vendor(id) ON DELETE SET NULL,
  creator TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  attrs JSONB NOT NULL DEFAULT '{}'::jsonb,
  base_key TEXT,
  ownership TEXT,
  customer_id TEXT,
  rma_no TEXT,
  linked_pn CHAR(12) REFERENCES part(pn) ON DELETE SET NULL,
  detail_prefix TEXT,
  detail_suffix TEXT,
  detail_code TEXT,
  rule_version TEXT,
  idempotency_key TEXT,
  note TEXT,
  source TEXT NOT NULL DEFAULT 'api',
  CONSTRAINT uq_cat_item_dash UNIQUE (cat_code, item, dash),
  CONSTRAINT ck_pn_format CHECK (pn ~ '^[0-9]{3}-[0-9]{4}-[0-9]{2}$'),
  CONSTRAINT ck_cat_matches_pn CHECK (substring(pn from 1 for 3) = cat_code),
  CONSTRAINT ck_item_bounds CHECK (item BETWEEN 0 AND 9999),
  CONSTRAINT ck_dash_bounds CHECK (dash BETWEEN 0 AND 99)
);

CREATE TABLE IF NOT EXISTS part_history (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  pn CHAR(12) NOT NULL REFERENCES part(pn) ON DELETE CASCADE,
  rev TEXT,
  change_note TEXT,
  state TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_by TEXT
);

CREATE TABLE IF NOT EXISTS reserved_numbers (
  cat_code CHAR(3) NOT NULL,
  item INT NOT NULL,
  dash INT,
  reason TEXT,
  reserved_by TEXT,
  reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (cat_code, item, dash)
);

CREATE TABLE IF NOT EXISTS counters (
  cat_code CHAR(3) PRIMARY KEY REFERENCES category(cat_code) ON DELETE CASCADE,
  next_item INT NOT NULL CHECK (next_item >= 0)
);

CREATE TABLE IF NOT EXISTS detail_counters (
  cat_code CHAR(3) NOT NULL REFERENCES category(cat_code) ON DELETE CASCADE,
  detail_prefix TEXT NOT NULL,
  next_suffix INT NOT NULL CHECK (next_suffix >= 0),
  PRIMARY KEY (cat_code, detail_prefix)
);

CREATE TABLE IF NOT EXISTS sample_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  pn CHAR(12) NOT NULL REFERENCES part(pn) ON DELETE CASCADE,
  state TEXT NOT NULL,
  note TEXT,
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  by_user TEXT
);

CREATE INDEX IF NOT EXISTS idx_part_cat_item ON part(cat_code, item);
CREATE INDEX IF NOT EXISTS idx_part_status ON part(status);
CREATE INDEX IF NOT EXISTS idx_part_base_key ON part USING gin (base_key gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_part_attrs ON part USING gin (attrs);
CREATE UNIQUE INDEX IF NOT EXISTS uq_part_idempotency ON part(idempotency_key) WHERE idempotency_key IS NOT NULL;

INSERT INTO series(series_code, name, owner_dept) VALUES
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
  (980, 'Engineering Sample (Alt)', 'Engineering/ADT')
ON CONFLICT (series_code) DO UPDATE SET name=EXCLUDED.name, owner_dept=EXCLUDED.owner_dept;

COMMIT;
