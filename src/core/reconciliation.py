from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.storage.storage import Storage


@dataclass
class ReconciliationStatus:
    healthy: bool
    open_orders: int
    inventory_count: int


class Reconciler:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def order_status_reconciliation(self, api_orders: list[dict[str, Any]]) -> int:
        updated = 0
        for order in api_orders:
            order_hash = order.get("order_hash")
            status = order.get("status", "UNKNOWN")
            if order_hash:
                self.storage.upsert_order(order_hash, status, order)
                updated += 1
        return updated

    def inventory_reconciliation(self, wallet_assets: list[dict[str, Any]]) -> int:
        self.storage.replace_inventory(wallet_assets)
        return len(wallet_assets)

    def health(self) -> ReconciliationStatus:
        open_orders = self.storage.count_open_orders()
        inv = self.storage.count_inventory()
        healthy = open_orders >= 0 and inv >= 0
        self.storage.log_reconciliation({"healthy": healthy, "open_orders": open_orders, "inventory": inv})
        return ReconciliationStatus(healthy=healthy, open_orders=open_orders, inventory_count=inv)
