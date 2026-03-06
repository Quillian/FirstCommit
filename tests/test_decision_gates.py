from src.core.decision_engine import DecisionEngine, MarketInputs


def cfg() -> dict:
    return {
        "size_controls": {"bid_size_eth": 0.01, "max_open_inventory": 1},
        "pricing": {"edge_buffer_pct": 0.02, "max_bid_price_eth": 0.02, "velocity_norm_denominator": 100},
        "fees": {"default_marketplace_bps": 250, "default_royalties_bps": 500},
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


def test_market_data_missing_blocks_live_gating() -> None:
    engine = DecisionEngine(cfg())
    inputs = MarketInputs(
        collection_slug="abc",
        verified=True,
        recent_sales=[],
        floor_asks=[],
        floor_bids=[],
        short_drift=0.0,
        sales_velocity=0.5,
        liquidity_score=0.8,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=1,
        inventory_age_sec=0,
    )
    decision = engine.evaluate(inputs, inventory_count=0, reconciliation_healthy=True, wallet_sufficient=True)
    assert decision["action"] == "DO_NOTHING"
    assert "market_data_missing" in decision["risk_flags"]


def test_dynamic_fees_used_in_expected_pnl() -> None:
    engine = DecisionEngine(cfg())
    inputs = MarketInputs(
        collection_slug="abc",
        verified=True,
        recent_sales=[1.2, 1.15, 1.18, 1.19, 1.22],
        floor_asks=[1.25, 1.3],
        floor_bids=[1.0, 0.98],
        short_drift=0.01,
        sales_velocity=0.7,
        liquidity_score=0.9,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=10,
        inventory_age_sec=0,
        marketplace_bps=0,
        royalties_bps=0,
    )
    decision = engine.evaluate(inputs, inventory_count=0, reconciliation_healthy=True, wallet_sufficient=True)
    assert decision["fees_bps"]["marketplace"] == 0
    assert decision["fees_bps"]["royalties"] == 0
