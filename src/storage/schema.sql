CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  collection_slug TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  collection_slug TEXT NOT NULL,
  price_eth REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  order_hash TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  side TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL,
  collection_slug TEXT,
  token_key TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_hash TEXT NOT NULL,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
  order_hash TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,
  collection_slug TEXT,
  token_key TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_hash TEXT,
  token_key TEXT,
  side TEXT NOT NULL,
  fill_price_eth REAL,
  source TEXT NOT NULL,
  ts TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
  token_key TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  collection_slug TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_key TEXT NOT NULL,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  collection_slug TEXT NOT NULL,
  decision_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pnl_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  collection_slug TEXT NOT NULL,
  pnl_eth REAL NOT NULL,
  context_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hourly_stats (
  hour_key TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_error_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  error_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  healthy INTEGER NOT NULL,
  pause_reason TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pause_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  reason TEXT NOT NULL,
  context_json TEXT NOT NULL
);
