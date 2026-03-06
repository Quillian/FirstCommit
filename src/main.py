from __future__ import annotations

import argparse
import json
import os
from typing import Any

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


def _to_float_list(values: list[Any], key: str | None = None) -> list[float]:
    out: list[float] = []
    for value in values:
        raw = value if key is None else value.get(key)
        try:
            out.append(float(raw))
        except (TypeError, ValueError):
            continue
    return out


def _extract_fee_bps(collection_details: dict[str, Any]) -> tuple[int | None, int | None]:
    fees = collection_details.get("fees") or {}
    opensea_fees = fees.get("opensea_fees") or {}
    seller_fees = fees.get("seller_fees") or {}
    marketplace = sum(int(float(item.get("fee", 0)) * 100) for item in opensea_fees.values()) if opensea_fees else None
    royalties = sum(int(float(item.get("fee", 0)) * 100) for item in seller_fees.values()) if seller_fees else None
    return marketplace, royalties


def market_from_opensea(client: OpenSeaClient, slug: str, cfg: dict[str, Any]) -> MarketInputs:
    details = client.get_collection_details(slug)
    stats = client.get_collection_stats(slug)
    events = client.get_events_by_collection(slug)
    best_listings = client.get_best_listings_by_collection(slug)
    all_listings = client.get_all_listings_by_collection(slug)
    all_offers = client.get_all_offers_by_collection(slug)

    sales = _to_float_list(events.get("asset_events", []), "payment_quantity")
    asks = _to_float_list(
        best_listings.get("listings", []) + all_listings.get("listings", []),
        "current_price",
    )
    bids = _to_float_list(all_offers.get("offers", []), "price")

    volume = float((stats.get("total") or {}).get("volume", 0.0))
    count = float((stats.get("total") or {}).get("count", 0.0))
    velocity = min(1.0, count / max(cfg["pricing"]["velocity_norm_denominator"], 1))
    liquidity = min(1.0, (volume / max(count, 1.0)) / max(asks[0] if asks else 1.0, 1e-9)) if count > 0 else 0.0

    marketplace_bps, royalties_bps = _extract_fee_bps(details)
    return MarketInputs(
        collection_slug=slug,
        verified=bool(details.get("collection", {}).get("safelist_status") in {"verified", "approved"}),
        recent_sales=sales,
        floor_asks=asks,
        floor_bids=bids,
        short_drift=0.0,
        sales_velocity=velocity,
        liquidity_score=liquidity,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=len(asks),
        inventory_age_sec=180,
        marketplace_bps=marketplace_bps,
        royalties_bps=royalties_bps,
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
    order_manager = OrderManager(
        client,
        signer,
        storage,
        ExecutionConfig(cfg["mode"], cfg["dry_run"], cfg["write_enabled"], cfg["opensea"]["chain"], cfg["opensea"]["protocol"]),
    )
    reconciler = Reconciler(storage)
    decision_engine = DecisionEngine(cfg)

    market = market_from_opensea(client, cfg["collections"]["allowlist"][0], cfg)
    if cfg["mode"] == "paper":
        PaperRunner(cfg, decision_engine, order_manager, storage, reconciler).run_once(market, wallet_sufficient=True)
    else:
        LiveRunner(cfg, client, decision_engine, order_manager, storage, reconciler).cycle(market)


if __name__ == "__main__":
    main()
