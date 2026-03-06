from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.regime import Regime


@dataclass
class RiskContext:
    verified: bool
    liquidity_score: float
    expected_net_pnl: float
    regime: Regime
    inventory_count: int
    max_inventory: int
    staircase_triggered: bool
    reconciliation_healthy: bool
    wallet_sufficient: bool


def evaluate_hard_gates(ctx: RiskContext) -> list[str]:
    flags: list[str] = []
    if not ctx.verified:
        flags.append("collection_not_verified")
    if ctx.liquidity_score < 0.55:
        flags.append("liquidity_weak")
    if ctx.expected_net_pnl < 0:
        flags.append("expected_net_pnl_negative")
    if ctx.regime == Regime.DEAD:
        flags.append("regime_dead")
    if ctx.inventory_count >= ctx.max_inventory:
        flags.append("inventory_limit_reached")
    if ctx.staircase_triggered:
        flags.append("staircase_down_filter")
    if not ctx.reconciliation_healthy:
        flags.append("reconciliation_unhealthy")
    if not ctx.wallet_sufficient:
        flags.append("insufficient_wallet_balance")
    return flags


def staircase_down_filter(recent_sales: list[float], threshold_pct: float) -> bool:
    if len(recent_sales) < 5:
        return False
    first = recent_sales[-5]
    last = recent_sales[-1]
    if first <= 0:
        return False
    return (first - last) / first >= threshold_pct
