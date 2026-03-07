from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, db_path: str, schema_path: str = "src/storage/schema.sql") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        schema = Path(schema_path).read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self._apply_migrations()
        self.conn.commit()

    def _apply_migrations(self) -> None:
        self._ensure_column("orders", "side", "TEXT NOT NULL DEFAULT 'unknown'")
        self._ensure_column("inventory", "status", "TEXT NOT NULL DEFAULT 'OPEN'")
        self._ensure_column("reconciliation_log", "healthy", "INTEGER NOT NULL DEFAULT 0")

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_order_status_history_order_hash ON order_status_history(order_hash)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fills_order_hash ON fills(order_hash)")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in columns}
        if column not in existing:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(payload: dict[str, Any] | list[Any] | None) -> str:
        return json.dumps(payload or {})

    def log_snapshot(self, collection_slug: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO snapshots(ts, collection_slug, payload_json) VALUES(?,?,?)",
            (self._now(), collection_slug, self._json(payload)),
        )
        self.conn.commit()

    def log_decision(self, collection_slug: str, decision: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO decisions(ts, collection_slug, decision_json) VALUES(?,?,?)",
            (self._now(), collection_slug, self._json(decision)),
        )
        self.conn.commit()

    def log_pause_reason(self, reason: str, context: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO pause_log(ts, reason, context_json) VALUES(?,?,?)",
            (self._now(), reason, self._json(context)),
        )
        self.conn.commit()

    def log_api_error(self, endpoint: str, error_text: str) -> None:
        self.conn.execute(
            "INSERT INTO api_error_log(ts, endpoint, error_text) VALUES(?,?,?)",
            (self._now(), endpoint, error_text),
        )
        self.conn.commit()

    def upsert_order(self, order_hash: str, status: str, payload: dict[str, Any], side: str = "unknown") -> None:
        collection_slug = payload.get("collection_slug") or payload.get("collection")
        token_key = payload.get("token_key")
        if not token_key:
            contract = payload.get("collection_contract") or payload.get("contract")
            token_id = payload.get("token_id")
            if contract is not None and token_id is not None:
                token_key = f"{contract}:{token_id}"

        self.conn.execute(
            """
            INSERT INTO orders(order_hash, ts, side, status, collection_slug, token_key, payload_json) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(order_hash) DO UPDATE SET
            ts=excluded.ts,
            side=excluded.side,
            status=excluded.status,
            collection_slug=excluded.collection_slug,
            token_key=excluded.token_key,
            payload_json=excluded.payload_json
            """,
            (order_hash, self._now(), side, status, collection_slug, token_key, self._json(payload)),
        )
        self.log_order_status(order_hash, status, source="order_upsert", payload=payload)

    def log_order_status(self, order_hash: str, status: str, source: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO order_status_history(order_hash, ts, status, source, payload_json) VALUES(?,?,?,?,?)",
            (order_hash, self._now(), status, source, self._json(payload)),
        )
        self.conn.commit()

    def upsert_listing(self, order_hash: str, status: str, payload: dict[str, Any]) -> None:
        collection_slug = payload.get("collection_slug") or payload.get("collection")
        token_key = payload.get("token_key")
        if not token_key:
            contract = payload.get("collection_contract") or payload.get("contract")
            token_id = payload.get("token_id")
            if contract is not None and token_id is not None:
                token_key = f"{contract}:{token_id}"

        self.conn.execute(
            """
            INSERT INTO listings(order_hash, ts, status, collection_slug, token_key, payload_json) VALUES(?,?,?,?,?,?)
            ON CONFLICT(order_hash) DO UPDATE SET
            ts=excluded.ts,
            status=excluded.status,
            collection_slug=excluded.collection_slug,
            token_key=excluded.token_key,
            payload_json=excluded.payload_json
            """,
            (order_hash, self._now(), status, collection_slug, token_key, self._json(payload)),
        )
        self.conn.commit()

    def record_fill(self, order_hash: str | None, token_key: str | None, side: str, fill_price_eth: float | None, source: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO fills(order_hash, token_key, side, fill_price_eth, source, ts, payload_json) VALUES(?,?,?,?,?,?,?)",
            (order_hash, token_key, side, fill_price_eth, source, self._now(), self._json(payload)),
        )
        self.conn.commit()

    def replace_inventory(self, assets: list[dict[str, Any]]) -> None:
        existing_rows = self.conn.execute("SELECT token_key FROM inventory WHERE status='OPEN'").fetchall()
        existing = {row["token_key"] for row in existing_rows}
        incoming: set[str] = set()

        for asset in assets:
            token_key = asset.get("token_key") or f"{asset.get('collection', 'unknown')}:{asset.get('token_id', 'na')}"
            incoming.add(token_key)
            slug = asset.get("collection", "unknown")
            self.conn.execute(
                """
                INSERT INTO inventory(token_key, ts, status, collection_slug, payload_json) VALUES(?,?,?,?,?)
                ON CONFLICT(token_key) DO UPDATE SET
                ts=excluded.ts,
                status='OPEN',
                collection_slug=excluded.collection_slug,
                payload_json=excluded.payload_json
                """,
                (token_key, self._now(), "OPEN", slug, self._json(asset)),
            )
            if token_key not in existing:
                self._log_inventory_event(token_key, "OPENED", asset)

        for token_key in existing - incoming:
            self.conn.execute("UPDATE inventory SET ts=?, status='CLOSED' WHERE token_key=?", (self._now(), token_key))
            self._log_inventory_event(token_key, "CLOSED", {"token_key": token_key})

        self.conn.commit()

    def _log_inventory_event(self, token_key: str, event_type: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO inventory_history(token_key, ts, event_type, payload_json) VALUES(?,?,?,?)",
            (token_key, self._now(), event_type, self._json(payload)),
        )

    def count_open_orders(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM orders WHERE status IN ('OPEN','PENDING','DRY_RUN')").fetchone()
        return int(row["c"] if row else 0)

    def count_open_bids(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as c FROM orders WHERE side='offer' AND status IN ('OPEN','PENDING','DRY_RUN')"
        ).fetchone()
        return int(row["c"] if row else 0)

    def count_open_listings(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM listings WHERE status IN ('OPEN','PENDING','DRY_RUN')").fetchone()
        return int(row["c"] if row else 0)

    def count_inventory(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM inventory WHERE status='OPEN'").fetchone()
        return int(row["c"] if row else 0)

    def count_fills(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM fills").fetchone()
        return int(row["c"] if row else 0)

    def log_reconciliation(self, payload: dict[str, Any]) -> None:
        healthy = 1 if payload.get("healthy") else 0
        pause_reason = payload.get("pause_reason")
        self.conn.execute(
            "INSERT INTO reconciliation_log(ts, healthy, pause_reason, payload_json) VALUES(?,?,?,?)",
            (self._now(), healthy, pause_reason, self._json(payload)),
        )
        self.conn.commit()
