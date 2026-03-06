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
    marketplace_bps: int | None = None
    royalties_bps: int | None = None


class DecisionEngine:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    def evaluate(self, inputs: MarketInputs, inventory_count: int, reconciliation_healthy: bool, wallet_sufficient: bool) -> dict[str, Any]:
        if not inputs.recent_sales or not inputs.floor_asks or not inputs.floor_bids:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "collection_slug": inputs.collection_slug,
                "action": "DO_NOTHING",
                "rationale": "blocked_market_data_missing",
                "risk_flags": ["market_data_missing"],
                "next_check_sec": self.cfg["throttling"]["scheduler_cycle_sec"],
            }

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

        target_bid = min(fair_value * (1 - self.cfg["pricing"]["edge_buffer_pct"]), max(inputs.floor_bids))
        bid_price = min(target_bid, self.cfg["pricing"]["max_bid_price_eth"])
        if bid_price > self.cfg["size_controls"]["bid_size_eth"]:
            bid_price = self.cfg["size_controls"]["bid_size_eth"]

        marketplace_bps = inputs.marketplace_bps if inputs.marketplace_bps is not None else self.cfg["fees"]["default_marketplace_bps"]
        royalties_bps = inputs.royalties_bps if inputs.royalties_bps is not None else self.cfg["fees"]["default_royalties_bps"]
        net = expected_net_pnl(
            bid_price=bid_price,
            expected_exit_price=expected_exit,
            marketplace_bps=marketplace_bps,
            royalties_bps=royalties_bps,
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
            "fees_bps": {"marketplace": marketplace_bps, "royalties": royalties_bps},
        }
