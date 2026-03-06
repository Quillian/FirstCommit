from src.core.decision_engine import DecisionEngine, MarketInputs


def cfg() -> dict:
    return {
        "size_controls": {"bid_size_eth": 0.01, "max_open_inventory": 1},
        "fees": {"marketplace_bps": 250, "royalties_bps": 500},
        "gas": {"per_trade_eth": 0.0008},
        "risk": {"staircase_drop_pct": 0.07},
        "throttling": {"scheduler_cycle_sec": 30},
    }


def test_expected_net_pnl_gate_blocks_negative() -> None:
    engine = DecisionEngine(cfg())
    inputs = MarketInputs(
        collection_slug="abc",
        verified=True,
        recent_sales=[0.004, 0.0039, 0.0038, 0.0037, 0.0036],
        floor_asks=[0.005, 0.0051],
        floor_bids=[0.0035, 0.0034],
        short_drift=-0.04,
        sales_velocity=0.2,
        liquidity_score=0.65,
        rank_in_ask_ladder=5,
        rank_in_book=5,
        local_depth=20,
        inventory_age_sec=10,
    )
    decision = engine.evaluate(inputs, inventory_count=0, reconciliation_healthy=True, wallet_sufficient=True)
    assert decision["action"] == "DO_NOTHING"
    assert "expected_net_pnl_negative" in decision["risk_flags"]
