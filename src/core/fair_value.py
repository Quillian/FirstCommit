from __future__ import annotations

from statistics import mean
from typing import Iterable


def _safe_mean(values: Iterable[float], default: float) -> float:
    v = [x for x in values if x > 0]
    return mean(v) if v else default


def compute_fair_value(
    recent_sales: list[float],
    floor_asks: list[float],
    floor_bids: list[float],
    short_drift: float,
    sales_velocity: float,
) -> float:
    sales_anchor = _safe_mean(recent_sales[-20:], default=0.0)
    ask_anchor = _safe_mean(floor_asks[:8], default=sales_anchor)
    bid_anchor = _safe_mean(floor_bids[:8], default=sales_anchor)

    velocity_boost = min(max((sales_velocity - 0.2) * 0.03, -0.02), 0.02)
    drift_boost = min(max(short_drift * 0.6, -0.04), 0.04)

    weighted = (sales_anchor * 0.45) + (ask_anchor * 0.3) + (bid_anchor * 0.25)
    return max(weighted * (1 + drift_boost + velocity_boost), 0.0)
