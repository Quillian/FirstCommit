from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.storage.storage import Storage

OPEN_STATUSES = {"OPEN", "PENDING", "DRY_RUN"}


@dataclass
class ReconciliationStatus:
    healthy: bool
    open_orders: int
    open_bids: int
    open_listings: int
    inventory_count: int
    fill_count: int
    reasons: list[str] = field(default_factory=list)


class Reconciler:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._state: dict[str, Any] = {
            "orders_seen": False,
            "listings_seen": False,
            "inventory_seen": False,
            "fills_seen": False,
            "expected_open_orders": 0,
            "expected_open_bids": 0,
            "expected_open_listings": 0,
            "expected_inventory": 0,
            "expected_fills": 0,
            "errors": [],
            "last_snapshot": {},
        }

    def _err(self, reason: str) -> None:
        if reason not in self._state["errors"]:
            self._state["errors"].append(reason)

    def _clear_error(self, reason: str) -> None:
        self._state["errors"] = [error for error in self._state["errors"] if error != reason]

    def order_status_reconciliation(self, api_orders: list[dict[str, Any]]) -> int:
        updated = 0
        try:
            for order in api_orders:
                order_hash = order.get("order_hash")
                status = str(order.get("status", "UNKNOWN")).upper()
                side = str(order.get("side", "offer"))
                if order_hash:
                    self.storage.upsert_order(order_hash, status, order, side=side)
                    updated += 1
            self._state["expected_open_orders"] = sum(1 for o in api_orders if str(o.get("status", "")).upper() in OPEN_STATUSES)
            self._state["expected_open_bids"] = sum(
                1
                for o in api_orders
                if str(o.get("status", "")).upper() in OPEN_STATUSES and str(o.get("side", "offer")) == "offer"
            )
            self._state["orders_seen"] = True
            self._clear_error("order_source_failed")
        except Exception:
            self._err("order_source_failed")
        return updated

    def listing_reconciliation(self, api_listings: list[dict[str, Any]]) -> int:
        updated = 0
        try:
            for listing in api_listings:
                order_hash = listing.get("order_hash")
                status = str(listing.get("status", "UNKNOWN")).upper()
                if order_hash:
                    self.storage.upsert_listing(order_hash, status, listing)
                    updated += 1
            self._state["expected_open_listings"] = sum(
                1 for listing in api_listings if str(listing.get("status", "")).upper() in OPEN_STATUSES
            )
            self._state["listings_seen"] = True
            self._clear_error("listing_source_failed")
        except Exception:
            self._err("listing_source_failed")
        return updated

    def inventory_reconciliation(self, wallet_assets: list[dict[str, Any]]) -> int:
        try:
            self.storage.replace_inventory(wallet_assets)
            self._state["expected_inventory"] = len(wallet_assets)
            self._state["inventory_seen"] = True
            self._clear_error("inventory_source_failed")
        except Exception:
            self._err("inventory_source_failed")
        return len(wallet_assets)

    def fills_reconciliation(self, api_fills: list[dict[str, Any]]) -> int:
        try:
            for fill in api_fills:
                self.storage.record_fill(
                    order_hash=fill.get("order_hash"),
                    token_key=fill.get("token_key"),
                    side=str(fill.get("side", "unknown")),
                    fill_price_eth=float(fill["fill_price_eth"]) if fill.get("fill_price_eth") is not None else None,
                    source="exchange",
                    payload=fill,
                )
            self._state["expected_fills"] = self.storage.count_fills()
            self._state["fills_seen"] = True
            self._clear_error("fill_source_failed")
        except Exception:
            self._err("fill_source_failed")
        return len(api_fills)

    def mark_missing_source(self, reason: str) -> None:
        self._err(reason)

    def health(self) -> ReconciliationStatus:
        open_orders = self.storage.count_open_orders()
        open_bids = self.storage.count_open_bids()
        open_listings = self.storage.count_open_listings()
        inventory = self.storage.count_inventory()
        fills = self.storage.count_fills()

        reasons: list[str] = []
        if not self._state["orders_seen"]:
            reasons.append("missing_open_order_source")
        if not self._state["listings_seen"]:
            reasons.append("missing_open_listing_source")
        if not self._state["inventory_seen"]:
            reasons.append("missing_inventory_source")
        if not self._state["fills_seen"]:
            reasons.append("missing_fill_source")

        if open_orders != self._state["expected_open_orders"]:
            reasons.append("open_order_mismatch")
        if open_bids != self._state["expected_open_bids"]:
            reasons.append("open_bid_mismatch")
        if open_listings != self._state["expected_open_listings"]:
            reasons.append("open_listing_mismatch")
        if inventory != self._state["expected_inventory"]:
            reasons.append("inventory_mismatch")
        if fills < self._state["expected_fills"]:
            reasons.append("fill_mismatch")

        reasons.extend(self._state["errors"])
        healthy = len(reasons) == 0

        payload = {
            "healthy": healthy,
            "open_orders": open_orders,
            "open_bids": open_bids,
            "open_listings": open_listings,
            "inventory": inventory,
            "fills": fills,
            "expected": {
                "open_orders": self._state["expected_open_orders"],
                "open_bids": self._state["expected_open_bids"],
                "open_listings": self._state["expected_open_listings"],
                "inventory": self._state["expected_inventory"],
            },
            "reasons": reasons,
            "pause_reason": "reconciliation_unhealthy" if not healthy else None,
        }
        self.storage.log_reconciliation(payload)
        return ReconciliationStatus(
            healthy=healthy,
            open_orders=open_orders,
            open_bids=open_bids,
            open_listings=open_listings,
            inventory_count=inventory,
            fill_count=fills,
            reasons=reasons,
        )
