import time

from src.execution.live_runner import RepriceGuard


def test_reprice_guard_blocks_churn() -> None:
    guard = RepriceGuard(material_change_pct=0.02, cooldown_sec=1000, max_per_hour=3)
    assert guard.should_reprice(1.0)
    guard.mark_reprice(1.0)
    assert not guard.should_reprice(1.03)


def test_reprice_guard_respects_max_window() -> None:
    guard = RepriceGuard(material_change_pct=0.01, cooldown_sec=0, max_per_hour=1)
    assert guard.should_reprice(1.0)
    guard.mark_reprice(1.0)
    assert not guard.should_reprice(1.05)
