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
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_snapshot(self, collection_slug: str, payload: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO snapshots(ts, collection_slug, payload_json) VALUES(?,?,?)", (self._now(), collection_slug, json.dumps(payload)))
        self.conn.commit()

    def log_decision(self, collection_slug: str, decision: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO decisions(ts, collection_slug, decision_json) VALUES(?,?,?)", (self._now(), collection_slug, json.dumps(decision)))
        self.conn.commit()

    def log_api_error(self, endpoint: str, error_text: str) -> None:
        self.conn.execute("INSERT INTO api_error_log(ts, endpoint, error_text) VALUES(?,?,?)", (self._now(), endpoint, error_text))
        self.conn.commit()

    def upsert_order(self, order_hash: str, status: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO orders(order_hash, ts, status, payload_json) VALUES(?,?,?,?)
            ON CONFLICT(order_hash) DO UPDATE SET ts=excluded.ts,status=excluded.status,payload_json=excluded.payload_json
            """,
            (order_hash, self._now(), status, json.dumps(payload)),
        )
        self.conn.commit()

    def replace_inventory(self, assets: list[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM inventory")
        for asset in assets:
            token_key = asset.get("token_key") or f"{asset.get('collection', 'unknown')}:{asset.get('token_id', 'na')}"
            slug = asset.get("collection", "unknown")
            self.conn.execute(
                "INSERT INTO inventory(token_key, ts, collection_slug, payload_json) VALUES(?,?,?,?)",
                (token_key, self._now(), slug, json.dumps(asset)),
            )
        self.conn.commit()

    def count_open_orders(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM orders WHERE status IN ('OPEN','PENDING')").fetchone()
        return int(row["c"] if row else 0)

    def count_inventory(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as c FROM inventory").fetchone()
        return int(row["c"] if row else 0)

    def log_reconciliation(self, payload: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO reconciliation_log(ts, payload_json) VALUES(?,?)", (self._now(), json.dumps(payload)))
        self.conn.commit()
