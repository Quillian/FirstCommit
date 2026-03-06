from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.core.edge_calc import compute_expected_exit_price, expected_net_pnl
from src.core.fair_value import compute_fair_value
from src.core.fill_model import estimate_fill
from src.core.regime import infer_regime
from src.core.risk_engine import RiskContext, evaluate_hard_gates, staircase_down_filter


@dataclass
class MarketInputs:
    collection_slug: str
    verified: bool
    recent_sales: list[float]
    floor_asks: list[float]
    floor_bids: list[float]
    short_drift: float
    sales_velocity: float
    liquidity_score: float
    rank_in_ask_ladder: int
    rank_in_book: int
    local_depth: int
    inventory_age_sec: int


class DecisionEngine:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def evaluate(self, inputs: MarketInputs, inventory_count: int, reconciliation_healthy: bool, wallet_sufficient: bool) -> dict[str, Any]:
        regime = infer_regime(inputs.sales_velocity, inputs.short_drift, inputs.liquidity_score)
        fair_value = compute_fair_value(
            inputs.recent_sales,
            inputs.floor_asks,
            inputs.floor_bids,
            inputs.short_drift,
            inputs.sales_velocity,
        )
        fill = estimate_fill(
            rank_in_ask_ladder=inputs.rank_in_ask_ladder,
            regime=regime,
            sales_velocity=inputs.sales_velocity,
            short_drift=inputs.short_drift,
            local_depth=inputs.local_depth,
            inventory_age_sec=inputs.inventory_age_sec,
        )
        expected_exit = compute_expected_exit_price(
            recent_sales_cluster=inputs.recent_sales,
            listing_ladder=inputs.floor_asks,
            rank_in_book=inputs.rank_in_book,
            regime=regime,
            drift=inputs.short_drift,
            fill_decay=max(0.0, 0.08 - (fill.fill_probability * 0.05)),
        )
        bid_price = min(fair_value * 0.98, self.cfg["size_controls"]["bid_size_eth"])
        net = expected_net_pnl(
            bid_price=bid_price,
            expected_exit_price=expected_exit,
            marketplace_bps=self.cfg["fees"]["marketplace_bps"],
            royalties_bps=self.cfg["fees"]["royalties_bps"],
            gas_eth=self.cfg["gas"]["per_trade_eth"],
        )
        risk_ctx = RiskContext(
            verified=inputs.verified,
            liquidity_score=inputs.liquidity_score,
            expected_net_pnl=net,
            regime=regime,
            inventory_count=inventory_count,
            max_inventory=self.cfg["size_controls"]["max_open_inventory"],
            staircase_triggered=staircase_down_filter(inputs.recent_sales, self.cfg["risk"]["staircase_drop_pct"]),
            reconciliation_healthy=reconciliation_healthy,
            wallet_sufficient=wallet_sufficient,
        )
        flags = evaluate_hard_gates(risk_ctx)
        action = "PLACE_BID" if not flags else "DO_NOTHING"
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collection_slug": inputs.collection_slug,
            "regime": regime.value,
            "fair_value": round(fair_value, 6),
            "expected_exit_price": round(expected_exit, 6),
            "expected_net_pnl": round(net, 6),
            "fill_probability": round(fill.fill_probability, 4),
            "action": action,
            "rationale": "all_hard_gates_passed" if action == "PLACE_BID" else "blocked_by_hard_gates",
            "risk_flags": flags,
            "next_check_sec": self.cfg["throttling"]["scheduler_cycle_sec"],
            "bid_price": round(max(0.0, bid_price), 6),
        }
