BEGIN;

CREATE TABLE IF NOT EXISTS counters (
  key TEXT PRIMARY KEY,
  val INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS parts (
  part_no TEXT PRIMARY KEY,
  series TEXT NOT NULL,
  serial INTEGER NOT NULL,
  revision TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  owner TEXT,
  series_name TEXT,
  note TEXT,
  rule_version TEXT,
  idempotency_key TEXT,
  source TEXT NOT NULL DEFAULT 'api'
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_parts_idem
  ON parts(idempotency_key) WHERE idempotency_key IS NOT NULL;

COMMIT;
