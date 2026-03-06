from __future__ import annotations

import argparse
import json
import os

from src.client.auth import AuthConfig, OpenSeaAuth
from src.client.opensea_client import OpenSeaClient
from src.client.rate_limiter import SlidingWindowRateLimiter
from src.core.decision_engine import DecisionEngine, MarketInputs
from src.core.reconciliation import Reconciler
from src.execution.live_runner import LiveRunner
from src.execution.order_manager import ExecutionConfig, OrderManager
from src.execution.paper_runner import PaperRunner
from src.execution.signer import Signer
from src.storage.storage import Storage
from src.utils.logging import configure_logging


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sample_market(slug: str) -> MarketInputs:
    return MarketInputs(
        collection_slug=slug,
        verified=True,
        recent_sales=[0.015, 0.0145, 0.0148, 0.0151, 0.0152],
        floor_asks=[0.016, 0.0161, 0.0163, 0.0165],
        floor_bids=[0.0138, 0.0137, 0.0135],
        short_drift=0.003,
        sales_velocity=0.6,
        liquidity_score=0.7,
        rank_in_ask_ladder=2,
        rank_in_book=2,
        local_depth=8,
        inventory_age_sec=180,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.getenv("AGENT_CONFIG_PATH", "config/agent.yaml"))
    args = parser.parse_args()
    cfg = load_config(args.config)
    configure_logging(cfg["logging"]["level"], cfg["logging"]["json"])

    storage = Storage(db_path=os.getenv("DB_PATH", "data/agent.sqlite3"))
    auth = OpenSeaAuth(AuthConfig(api_key_env=cfg["opensea"]["api_key_env"]))
    client = OpenSeaClient(
        base_url=cfg["opensea"]["api_base_url"],
        auth=auth,
        rate_limiter=SlidingWindowRateLimiter(cfg["throttling"]["max_requests_per_minute"]),
        timeout_sec=cfg["opensea"]["request_timeout_sec"],
        retry_attempts=cfg["opensea"]["retry_attempts"],
    )
    signer = Signer(private_key=os.getenv(cfg["wallet"]["private_key_env"]))
    order_manager = OrderManager(client, signer, storage, ExecutionConfig(cfg["mode"], cfg["dry_run"], cfg["write_enabled"]))
    reconciler = Reconciler(storage)
    decision_engine = DecisionEngine(cfg)

    market = sample_market(cfg["collections"]["allowlist"][0])
    if cfg["mode"] == "paper":
        PaperRunner(cfg, decision_engine, order_manager, storage, reconciler).run_once(market, wallet_sufficient=True)
    else:
        LiveRunner(cfg, decision_engine, order_manager, storage, reconciler).cycle(market)


if __name__ == "__main__":
    main()
