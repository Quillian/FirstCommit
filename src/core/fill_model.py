from __future__ import annotations

from dataclasses import dataclass

from src.core.regime import Regime


@dataclass
class FillEstimate:
    fill_probability: float
    expected_time_to_fill_sec: int


def estimate_fill(
    rank_in_ask_ladder: int,
    regime: Regime,
    sales_velocity: float,
    short_drift: float,
    local_depth: int,
    inventory_age_sec: int,
) -> FillEstimate:
    regime_factor = {
        Regime.DEAD: 0.2,
        Regime.WEAK: 0.45,
        Regime.NEUTRAL: 0.65,
        Regime.HEALTHY: 0.85,
    }[regime]
    rank_penalty = min(rank_in_ask_ladder * 0.08, 0.6)
    depth_penalty = min(local_depth * 0.02, 0.3)
    age_boost = min(inventory_age_sec / 3600 * 0.03, 0.2)
    drift_boost = max(min(short_drift * 0.8, 0.2), -0.2)
    velocity_boost = min(sales_velocity * 0.25, 0.2)

    prob = regime_factor - rank_penalty - depth_penalty + age_boost + drift_boost + velocity_boost
    prob = max(0.01, min(prob, 0.98))

    expected_time = int(max(120, 7200 * (1 - prob)))
    return FillEstimate(fill_probability=prob, expected_time_to_fill_sec=expected_time)
