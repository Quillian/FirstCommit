from __future__ import annotations

import json
import logging
from typing import Any

from src.core.decision_engine import DecisionEngine, MarketInputs
from src.core.reconciliation import Reconciler
from src.core.state_machine import DeterministicStateMachine
from src.execution.order_manager import OrderManager
from src.storage.storage import Storage

logger = logging.getLogger(__name__)


class PaperRunner:
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
        self.sm = DeterministicStateMachine()

    def run_once(self, market: MarketInputs, wallet_sufficient: bool = True) -> dict[str, Any]:
        self.sm.advance("collection_selected")
        self.sm.advance("qualified")
        reconciliation_healthy = self.reconciler.health().healthy
        decision = self.decision_engine.evaluate(
            market,
            inventory_count=self.storage.count_inventory(),
            reconciliation_healthy=reconciliation_healthy,
            wallet_sufficient=wallet_sufficient,
        )
        if decision["action"] == "PLACE_BID":
            self.sm.advance("bid_submitted")
            payload = self.order_manager.build_offer_payload(
                market.collection_slug,
                decision["bid_price"],
                "paper_wallet",
                "0x0000000000000000000000000000000000000001",
                "0x0000000000000000000000000000000000000002",
            )
            result = self.order_manager.create_offer(payload)
            decision["write_result"] = result
        else:
            self.sm.advance("blocked")
        decision["state"] = self.sm.state.value
        self.storage.log_decision(market.collection_slug, decision)
        logger.info(json.dumps(decision))
        return decision
