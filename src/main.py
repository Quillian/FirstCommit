from __future__ import annotations

import argparse
import json
import os
from typing import Any

from src.client.auth import AuthConfig, OpenSeaAuth
from src.client.opensea_client import OpenSeaClient, OpenSeaClientError
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


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, dict):
        current = raw.get("current")
        if isinstance(current, dict):
            raw = current
        if isinstance(raw.get("value"), (str, int, float)) and isinstance(raw.get("decimals"), int):
            try:
                return float(raw.get("value")) / (10 ** int(raw.get("decimals")))
            except (TypeError, ValueError):
                return None
        for candidate in (
            raw.get("eth"),
            raw.get("quantity"),
            raw.get("value"),
            raw.get("amount"),
        ):
            if candidate is not None:
                raw = candidate
                break
        if isinstance(raw, (int, float)):
            return float(raw)

        decimals = raw.get("decimals") if isinstance(raw, dict) else None
        value = raw.get("value") if isinstance(raw, dict) else None
        if value is not None:
            try:
                as_float = float(value)
                if isinstance(decimals, int) and decimals >= 0:
                    return as_float / (10 ** decimals)
                return as_float
            except (TypeError, ValueError):
                return None

    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _to_float_list(values: list[Any], key: str | None = None) -> list[float]:
    out: list[float] = []
    for value in values:
        raw = value if key is None else value.get(key)
        parsed = _to_float(raw)
        if parsed is None:
            continue
        out.append(parsed)
    return out


def _first_by_path(container: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current = container
        for segment in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(segment)
        if current is not None:
            return current
    return None


def _extract_fee_bps(collection_details: dict[str, Any]) -> tuple[int | None, int | None]:
    fees = _first_by_path(collection_details, ("fees",), ("collection", "fees")) or {}
    opensea_fees = fees.get("opensea_fees") or []
    seller_fees = fees.get("seller_fees") or []

    if isinstance(opensea_fees, dict):
        opensea_values = opensea_fees.values()
    else:
        opensea_values = opensea_fees

    if isinstance(seller_fees, dict):
        seller_values = seller_fees.values()
    else:
        seller_values = seller_fees

    marketplace_items = [item for item in opensea_values if isinstance(item, dict)]
    royalty_items = [item for item in seller_values if isinstance(item, dict)]
    def _fee_item_bps(item: dict[str, Any]) -> int:
        fee = _first_by_path(item, ("fee",), ("basis_points",), ("bps",))
        if fee is None:
            return 0
        as_float = float(fee)
        if as_float > 100:
            return int(as_float)
        return int(as_float * 100)

    marketplace = sum(_fee_item_bps(item) for item in marketplace_items) if marketplace_items else None
    royalties = sum(_fee_item_bps(item) for item in royalty_items) if royalty_items else None
    return marketplace, royalties


def _extract_fee_recipients(collection_details: dict[str, Any]) -> list[dict[str, Any]]:
    fees = _first_by_path(collection_details, ("fees",), ("collection", "fees")) or {}
    recipients: list[dict[str, Any]] = []
    for bucket in (fees.get("opensea_fees") or {}, fees.get("seller_fees") or {}):
        rows = bucket.values() if isinstance(bucket, dict) else bucket
        for item in rows:
            if not isinstance(item, dict):
                continue
            recipient = str(item.get("recipient") or item.get("address") or "").strip()
            if not recipient:
                continue
            fee = _first_by_path(item, ("fee",), ("basis_points",), ("bps",))
            if fee is None:
                continue
            fee_float = float(fee)
            bps = int(fee_float if fee_float > 100 else fee_float * 100)
            if bps <= 0:
                continue
            recipients.append({"recipient": recipient, "bps": bps})
    return recipients


def _extract_asset_identity(*payloads: dict[str, Any]) -> tuple[str | None, str | None]:
    def _dict_value(container: Any, key: str) -> Any:
        if not isinstance(container, dict):
            return None
        return container.get(key)

    def _is_invalid_placeholder(candidate: Any) -> bool:
        if candidate is None:
            return True
        if isinstance(candidate, bool):
            return True
        if isinstance(candidate, str):
            return candidate.strip() == ""
        if isinstance(candidate, (dict, list, tuple, set)):
            return True
        return False

    def _pick_value(*candidates: Any) -> Any:
        for candidate in candidates:
            if _is_invalid_placeholder(candidate):
                continue
            return candidate
        return None

    for payload in payloads:
        for key in ("listings", "offers", "asset_events", "assets", "nfts"):
            for row in payload.get(key) or []:
                asset_contract = _dict_value(row, "asset_contract")
                asset = _dict_value(row, "asset")
                contract = _pick_value(
                    row.get("contract"),
                    row.get("contract_address"),
                    _dict_value(asset_contract, "address"),
                    _dict_value(_dict_value(asset, "asset_contract"), "address"),
                )
                token_id = _pick_value(
                    row.get("token_id"),
                    row.get("identifier"),
                    _dict_value(asset, "token_id"),
                )
                if contract is not None and token_id is not None:
                    return str(contract), str(token_id)
    return None, None


def market_from_opensea(client: OpenSeaClient, slug: str, cfg: dict[str, Any]) -> MarketInputs:
    details = client.get_collection_details(slug)
    stats = client.get_collection_stats(slug)
    events = client.get_events_by_collection(slug)
    best_listings = client.get_best_listings_by_collection(slug)
    all_listings = client.get_all_listings_by_collection(slug)
    all_offers = client.get_all_offers_by_collection(slug)

    sales_payload = events.get("asset_events", [])
    sales: list[float] = []
    for sale_row in sales_payload:
        raw_sale_value = _first_by_path(
            sale_row,
            ("payment_quantity",),
            ("payment",),
            ("payment", "quantity"),
            ("sale_price",),
            ("total_price",),
            ("price",),
        )
        parsed = _to_float(raw_sale_value)
        if parsed is not None:
            sales.append(parsed)

    asks: list[float] = []
    for listing in best_listings.get("listings", []) + all_listings.get("listings", []):
        raw_ask_value = _first_by_path(
            listing,
            ("current_price",),
            ("price",),
            ("price", "current"),
            ("base_price",),
            ("starting_price",),
        )
        parsed = _to_float(raw_ask_value)
        if parsed is not None:
            asks.append(parsed)
    bids = _to_float_list(all_offers.get("offers", []), "price")

    total_stats = stats.get("total") or {}
    volume = float(_first_by_path(stats, ("total", "volume"), ("volume",), ("stats", "volume")) or 0.0)
    count = float(
        _first_by_path(
            stats,
            ("total", "count"),
            ("total", "sales"),
            ("count",),
            ("sales",),
            ("stats", "count"),
            ("stats", "sales"),
        )
        or 0.0
    )
    velocity = min(1.0, count / max(cfg["pricing"]["velocity_norm_denominator"], 1))
    liquidity = min(1.0, (volume / max(count, 1.0)) / max(asks[0] if asks else 1.0, 1e-9)) if count > 0 else 0.0

    marketplace_bps, royalties_bps = _extract_fee_bps(details)
    fee_recipients = _extract_fee_recipients(details)
    target_collection_contract, target_token_id = _extract_asset_identity(best_listings, all_listings, all_offers, events)
    return MarketInputs(
        collection_slug=slug,
        verified=bool(
            _first_by_path(
                details,
                ("collection", "safelist_status"),
                ("safelist_status",),
                ("collection", "verification_status"),
                ("verification_status",),
                ("collection", "is_verified"),
                ("is_verified",),
                ("collection", "details", "collection", "safelist_status"),
            )
            in {"verified", "approved", "is_verified", True}
        ),
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
        fee_recipients=fee_recipients,
        target_collection_contract=target_collection_contract,
        target_token_id=target_token_id,
    )


def _market_data_healthy(market: MarketInputs) -> bool:
    return bool(market.recent_sales and market.floor_asks and market.floor_bids)


def _live_fee_data_healthy(market: MarketInputs, cfg: dict[str, Any]) -> bool:
    if cfg["mode"] != "live" or not cfg["fees"].get("use_collection_fees", True):
        return True
    return market.marketplace_bps is not None and market.royalties_bps is not None and bool(market.fee_recipients)


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

    slug = cfg["collections"]["allowlist"][0]
    try:
        market = market_from_opensea(client, slug, cfg)
    except OpenSeaClientError as exc:
        if cfg["mode"] == "live":
            raise RuntimeError(f"live_launch_blocked_market_ingest_failed={exc}") from exc
        market = MarketInputs(
            collection_slug=slug,
            verified=False,
            recent_sales=[],
            floor_asks=[],
            floor_bids=[],
            short_drift=0.0,
            sales_velocity=0.0,
            liquidity_score=0.0,
            rank_in_ask_ladder=1,
            rank_in_book=1,
            local_depth=0,
            inventory_age_sec=0,
            fee_recipients=[],
        )

    if cfg["mode"] == "paper":
        PaperRunner(cfg, decision_engine, order_manager, storage, reconciler).run_once(market, wallet_sufficient=True)
        return

    if not _live_fee_data_healthy(market, cfg):
        storage.log_pause_reason("missing_dynamic_fees", {"collection": slug})
        raise RuntimeError("live_launch_blocked_collection_fees_unavailable")

    if not _market_data_healthy(market):
        storage.log_pause_reason("invalid_market_data", {"collection": slug})
        raise RuntimeError("live_launch_blocked_market_data_unavailable")

    live_runner = LiveRunner(cfg, client, decision_engine, order_manager, storage, reconciler)
    cycles = int(cfg.get("runtime", {}).get("cycle_count", 10 if cfg.get("dry_run") else 1))
    for _ in range(max(1, cycles)):
        live_runner.cycle(market)


if __name__ == "__main__":
    main()
