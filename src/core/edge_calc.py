from __future__ import annotations

from dataclasses import dataclass

from src.core.regime import Regime


@dataclass
class EdgeResult:
    expected_exit_price: float
    expected_net_pnl: float


def compute_expected_exit_price(
    recent_sales_cluster: list[float],
    listing_ladder: list[float],
    rank_in_book: int,
    regime: Regime,
    drift: float,
    fill_decay: float,
) -> float:
    sales_cluster = sum(recent_sales_cluster[:10]) / max(len(recent_sales_cluster[:10]), 1)
    ladder_anchor = sum(listing_ladder[:10]) / max(len(listing_ladder[:10]), 1)
    base = (sales_cluster * 0.55) + (ladder_anchor * 0.45)
    rank_penalty = min(rank_in_book * 0.004, 0.04)
    regime_factor = {Regime.DEAD: -0.06, Regime.WEAK: -0.03, Regime.NEUTRAL: 0.0, Regime.HEALTHY: 0.02}[regime]
    adjusted = base * (1 + regime_factor + drift * 0.5 - fill_decay - rank_penalty)
    return max(adjusted, 0.0)


def expected_net_pnl(
    bid_price: float,
    expected_exit_price: float,
    marketplace_bps: int,
    royalties_bps: int,
    gas_eth: float,
) -> float:
    total_fee = (marketplace_bps + royalties_bps) / 10_000
    net_exit = expected_exit_price * (1 - total_fee)
    return net_exit - bid_price - gas_eth
