from __future__ import annotations

import os
import time
from collections import deque
from typing import Any

from src.core.decision_engine import DecisionEngine, MarketInputs
from src.core.reconciliation import Reconciler
from src.execution.order_manager import OrderManager
from src.storage.storage import Storage


class RepriceGuard:
    def __init__(self, material_change_pct: float, cooldown_sec: int, max_per_hour: int) -> None:
        self.material_change_pct = material_change_pct
        self.cooldown_sec = cooldown_sec
        self.max_per_hour = max_per_hour
        self.last_price: float | None = None
        self.last_reprice_ts = 0.0
        self.reprices: deque[float] = deque()

    def should_reprice(self, new_price: float) -> bool:
        now = time.time()
        while self.reprices and now - self.reprices[0] > 3600:
            self.reprices.popleft()
        if len(self.reprices) >= self.max_per_hour:
            return False
        if now - self.last_reprice_ts < self.cooldown_sec:
            return False
        if self.last_price is None:
            return True
        change = abs(new_price - self.last_price) / max(self.last_price, 1e-9)
        return change >= self.material_change_pct

    def mark_reprice(self, price: float) -> None:
        self.last_price = price
        self.last_reprice_ts = time.time()
        self.reprices.append(self.last_reprice_ts)


class LiveRunner:
    def __init__(
        self,
        cfg: dict[str, Any],
        decision_engine: DecisionEngine,
        order_manager: OrderManager,
        storage: Storage,
        reconciler: Reconciler,
    ) -> None:
        self.cfg = cfg
        self.decision_engine = decision_engine
        self.order_manager = order_manager
        self.storage = storage
        self.reconciler = reconciler
        self.guard = RepriceGuard(
            cfg["repricing"]["material_change_pct"],
            cfg["repricing"]["cooldown_sec"],
            cfg["repricing"]["max_reprices_per_hour"],
        )

    def check_wallet_balance(self) -> bool:
        # Placeholder deterministic check for tiny-live v1; replace with RPC call in deployment.
        bal = float(os.getenv("SIM_WALLET_BALANCE_ETH", "1.0"))
        return bal >= float(self.cfg["wallet"]["min_native_balance_eth"])

    def cycle(self, market: MarketInputs) -> dict[str, Any]:
        wallet_ok = self.check_wallet_balance()
        reconciliation_healthy = self.reconciler.health().healthy
        decision = self.decision_engine.evaluate(
            market,
            inventory_count=self.storage.count_inventory(),
            reconciliation_healthy=reconciliation_healthy,
            wallet_sufficient=wallet_ok,
        )
        self.storage.log_decision(market.collection_slug, decision)

        if decision["action"] == "PLACE_BID":
            payload = self.order_manager.build_offer_payload(market.collection_slug, decision["bid_price"], os.getenv("WALLET_ADDRESS", ""))
            decision["offer_result"] = self.order_manager.create_offer(payload)

        return decision
