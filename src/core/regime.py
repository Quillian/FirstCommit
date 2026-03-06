from __future__ import annotations

from enum import Enum


class Regime(str, Enum):
    DEAD = "DEAD"
    WEAK = "WEAK"
    NEUTRAL = "NEUTRAL"
    HEALTHY = "HEALTHY"


def infer_regime(sales_velocity: float, short_drift: float, liquidity_score: float) -> Regime:
    if liquidity_score < 0.25 or sales_velocity < 0.05:
        return Regime.DEAD
    if liquidity_score < 0.45 or short_drift < -0.03:
        return Regime.WEAK
    if liquidity_score > 0.7 and short_drift >= 0:
        return Regime.HEALTHY
    return Regime.NEUTRAL
