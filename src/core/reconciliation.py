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
        self._orders_reconciled = False
        self._inventory_reconciled = False
        self._expected_open_orders = 0
        self._expected_inventory = 0
        self._last_error: str | None = None

    def order_status_reconciliation(self, api_orders: list[dict[str, Any]]) -> int:
        updated = 0
        try:
            for order in api_orders:
                order_hash = order.get("order_hash")
                status = order.get("status", "UNKNOWN")
                if order_hash:
                    self.storage.upsert_order(order_hash, status, order)
                    updated += 1

            self._expected_open_orders = sum(
                1 for order in api_orders if order.get("status", "UNKNOWN") in {"OPEN", "PENDING"}
            )
            self._orders_reconciled = True
            self._last_error = None
        except Exception as exc:
            self._orders_reconciled = True
            self._expected_open_orders = -1
            self._last_error = str(exc)
        return updated

    def inventory_reconciliation(self, wallet_assets: list[dict[str, Any]]) -> int:
        try:
            self.storage.replace_inventory(wallet_assets)
            self._expected_inventory = len(wallet_assets)
            self._inventory_reconciled = True
            self._last_error = None
        except Exception as exc:
            self._inventory_reconciled = True
            self._expected_inventory = -1
            self._last_error = str(exc)
        return len(wallet_assets)

    def health(self) -> ReconciliationStatus:
        open_orders = self.storage.count_open_orders()
        inv = self.storage.count_inventory()
        orders_in_sync = self._orders_reconciled and open_orders == self._expected_open_orders
        inventory_in_sync = self._inventory_reconciled and inv == self._expected_inventory
        healthy = self._last_error is None and orders_in_sync and inventory_in_sync
        self.storage.log_reconciliation(
            {
                "healthy": healthy,
                "open_orders": open_orders,
                "inventory": inv,
                "orders_reconciled": self._orders_reconciled,
                "inventory_reconciled": self._inventory_reconciled,
                "orders_in_sync": orders_in_sync,
                "inventory_in_sync": inventory_in_sync,
                "last_error": self._last_error,
            }
        )
        return ReconciliationStatus(healthy=healthy, open_orders=open_orders, inventory_count=inv)
