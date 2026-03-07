from __future__ import annotations

import json

import pytest

from src import main
from src.client.opensea_client import OpenSeaClientError
from src.core.decision_engine import MarketInputs


class FakeClient:
    def __init__(self) -> None:
        self.called: list[str] = []

    def get_collection_details(self, slug: str):
        self.called.append("details")
        return {
            "collection": {"safelist_status": "verified"},
            "fees": {
                "opensea_fees": {"opensea": {"fee": 2.5}},
                "seller_fees": {"creator": {"fee": 5.0}},
            },
        }

    def get_collection_stats(self, slug: str):
        self.called.append("stats")
        return {"total": {"volume": 100, "count": 10}}

    def get_events_by_collection(self, slug: str):
        self.called.append("events")
        return {"asset_events": [{"payment_quantity": "1.0"}]}

    def get_best_listings_by_collection(self, slug: str):
        self.called.append("best_listings")
        return {"listings": [{"current_price": "1.1"}]}

    def get_all_listings_by_collection(self, slug: str):
        self.called.append("all_listings")
        return {"listings": [{"current_price": "1.2"}]}

    def get_all_offers_by_collection(self, slug: str):
        self.called.append("all_offers")
        return {"offers": [{"price": "1.0"}]}


class FailingClient:
    def get_collection_details(self, slug: str):
        raise OpenSeaClientError("GET", "/collections/x", 500, "boom")


def test_market_from_opensea_uses_all_live_endpoints() -> None:
    cfg = {"pricing": {"velocity_norm_denominator": 100}}
    client = FakeClient()

    market = main.market_from_opensea(client, "cool", cfg)

    assert set(client.called) == {"details", "stats", "events", "best_listings", "all_listings", "all_offers"}
    assert market.marketplace_bps == 250
    assert market.royalties_bps == 500
    assert market.floor_asks and market.floor_bids and market.recent_sales


def test_live_market_ingest_failure_blocks_launch(monkeypatch, tmp_path) -> None:
    config = {
        "mode": "live",
        "write_enabled": False,
        "dry_run": True,
        "wallet": {"address_env": "WALLET_ADDRESS", "private_key_env": "PRIVATE_KEY", "min_native_balance_eth": 0.02},
        "opensea": {
            "api_base_url": "https://api.opensea.io/api/v2",
            "stream_url": "wss://stream.openseabeta.com/socket",
            "api_key_env": "OPENSEA_API_KEY",
            "request_timeout_sec": 10,
            "retry_attempts": 1,
            "chain": "ethereum",
            "protocol": "seaport",
        },
        "collections": {"allowlist": ["cool"], "require_verified": True},
        "size_controls": {"max_open_inventory": 1, "bid_size_eth": 0.01, "max_daily_spend_eth": 0.03},
        "pricing": {"edge_buffer_pct": 0.02, "max_bid_price_eth": 0.02, "velocity_norm_denominator": 100},
        "fees": {"use_collection_fees": True, "default_marketplace_bps": 250, "default_royalties_bps": 500},
        "gas": {"per_trade_eth": 0.0008},
        "risk": {"min_liquidity_score": 0.55, "staircase_drop_pct": 0.07, "unhealthy_error_rate": 0.15, "pause_after_consecutive_errors": 5},
        "repricing": {"material_change_pct": 0.015, "cooldown_sec": 120, "max_reprices_per_hour": 3},
        "throttling": {"max_requests_per_minute": 60, "scheduler_cycle_sec": 30},
        "logging": {"json": True, "level": "INFO"},
    }
    cfg_path = tmp_path / "agent.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setattr(main, "OpenSeaClient", lambda *args, **kwargs: FailingClient())
    monkeypatch.setattr("sys.argv", ["main", "--config", str(cfg_path)])

    with pytest.raises(RuntimeError, match="live_launch_blocked_market_ingest_failed"):
        main.main()


def test_market_health_guard() -> None:
    market = MarketInputs(
        collection_slug="x",
        verified=True,
        recent_sales=[1.0],
        floor_asks=[1.1],
        floor_bids=[0.9],
        short_drift=0.0,
        sales_velocity=0.5,
        liquidity_score=0.5,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=1,
        inventory_age_sec=0,
    )
    assert main._market_data_healthy(market) is True
    market.floor_bids = []
    assert main._market_data_healthy(market) is False
