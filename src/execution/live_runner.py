from __future__ import annotations

import json
import os
import time
from collections import deque
from decimal import Decimal
from typing import Any
from urllib.request import Request, urlopen

from src.client.opensea_client import OpenSeaClient
from src.core.decision_engine import DecisionEngine, MarketInputs
from src.core.reconciliation import Reconciler
from src.execution.order_manager import OrderManager
from src.storage.storage import Storage


class RepriceGuard:
    def __init__(self, material_change_pct: float, cooldown_sec: int, max_per_hour: int) -> None:
        self.material_change_pct = material_change_pct
        self.cooldown_sec = cooldown_sec
        self.max_per_hour = max_per_hour
        self.last_price: float | None = None
        self.last_reprice_ts = 0.0
        self.reprices: deque[float] = deque()

    def should_reprice(self, new_price: float) -> bool:
        now = time.time()
        while self.reprices and now - self.reprices[0] > 3600:
            self.reprices.popleft()
        if len(self.reprices) >= self.max_per_hour:
            return False
        if now - self.last_reprice_ts < self.cooldown_sec:
            return False
        if self.last_price is None:
            return True
        change = abs(new_price - self.last_price) / max(self.last_price, 1e-9)
        return change >= self.material_change_pct

    def mark_reprice(self, price: float) -> None:
        self.last_price = price
        self.last_reprice_ts = time.time()
        self.reprices.append(self.last_reprice_ts)


class LiveRunner:
    def __init__(
        self,
        cfg: dict[str, Any],
        client: OpenSeaClient,
        decision_engine: DecisionEngine,
        order_manager: OrderManager,
        storage: Storage,
        reconciler: Reconciler,
    ) -> None:
        self.cfg = cfg
        self.client = client
        self.decision_engine = decision_engine
        self.order_manager = order_manager
        self.storage = storage
        self.reconciler = reconciler
        self.guard = RepriceGuard(
            cfg["repricing"]["material_change_pct"],
            cfg["repricing"]["cooldown_sec"],
            cfg["repricing"]["max_reprices_per_hour"],
        )

    def check_wallet_balance(self) -> bool:
        rpc = os.getenv("RPC_URL")
        wallet = os.getenv(self.cfg["wallet"]["address_env"], "")
        if not rpc or not wallet:
            return False

        req = Request(
            rpc,
            method="POST",
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [wallet, "latest"], "id": 1}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        wei = int(payload.get("result", "0x0"), 16)
        eth = float(Decimal(wei) / Decimal(10**18))
        return eth >= float(self.cfg["wallet"]["min_native_balance_eth"])

    @staticmethod
    def _extract_order_rows(payload: dict[str, Any], side: str) -> list[dict[str, Any]]:
        rows = payload.get("orders") or payload.get("listings") or payload.get("offers") or []
        normalized: list[dict[str, Any]] = []
        for row in rows:
            order_hash = row.get("order_hash") or row.get("orderHash")
            status = row.get("status") or ("OPEN" if row.get("is_valid", True) else "CANCELLED")
            if order_hash:
                normalized.append({"order_hash": order_hash, "status": str(status).upper(), "side": side, **row})
        return normalized

    @staticmethod
    def _extract_inventory_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        assets = payload.get("nfts") or payload.get("assets") or []
        normalized: list[dict[str, Any]] = []
        for asset in assets:
            contract = asset.get("contract") or asset.get("contract_address") or "unknown"
            token_id = str(asset.get("identifier") or asset.get("token_id") or "")
            normalized.append(
                {"token_key": f"{contract}:{token_id}", "collection": contract, "token_id": token_id, **asset}
            )
        return normalized

    def reconcile_account_state(self) -> None:
        slug = self.cfg["collections"]["allowlist"][0]
        listings = self.client.get_all_listings_by_collection(slug)
        offers = self.client.get_all_offers_by_collection(slug)
        listing_rows = self._extract_order_rows(listings, side="listing")
        offer_rows = self._extract_order_rows(offers, side="offer")
        self.reconciler.order_status_reconciliation(offer_rows + listing_rows)
        self.reconciler.listing_reconciliation(listing_rows)

        events = self.client.get_events_by_collection(slug)
        fills = []
        for event in events.get("asset_events", []):
            if str(event.get("event_type", "")).lower() in {"sale", "successful"}:
                fills.append(
                    {
                        "order_hash": event.get("order_hash") or event.get("orderHash"),
                        "token_key": f"{event.get('contract_address', 'unknown')}:{event.get('token_id', '')}",
                        "side": "offer",
                        "fill_price_eth": float(event.get("payment_quantity", 0) or 0),
                    }
                )
        self.reconciler.fills_reconciliation(fills)

        wallet = os.getenv(self.cfg["wallet"]["address_env"], "")
        if wallet:
            inv_payload = self.client.get_account_nfts(self.cfg["opensea"]["chain"], wallet)
            self.reconciler.inventory_reconciliation(self._extract_inventory_rows(inv_payload))
        else:
            self.reconciler.mark_missing_source("missing_wallet_address")

    def cycle(self, market: MarketInputs) -> dict[str, Any]:
        self.reconcile_account_state()
        wallet_ok = self.check_wallet_balance()
        reconciliation_status = self.reconciler.health()
        decision = self.decision_engine.evaluate(
            market,
            inventory_count=self.storage.count_inventory(),
            reconciliation_healthy=reconciliation_status.healthy,
            wallet_sufficient=wallet_ok,
        )

        if not self.order_manager.signer.private_key and self.cfg.get("mode") == "live":
            decision["action"] = "DO_NOTHING"
            decision.setdefault("risk_flags", []).append("signer_unavailable")

        if decision["action"] == "PLACE_BID":
            if not market.target_collection_contract or not market.target_token_id:
                decision["action"] = "DO_NOTHING"
                decision["rationale"] = "blocked_missing_target_asset_identity"
                decision.setdefault("risk_flags", []).append("missing_target_asset_identity")
            else:
                payload = self.order_manager.build_offer_payload(
                    market.collection_slug,
                    market.target_collection_contract,
                    market.target_token_id,
                    decision["bid_price"],
                    os.getenv("WALLET_ADDRESS", ""),
                    fee_recipients=market.fee_recipients,
                )
                decision["offer_result"] = self.order_manager.create_offer(payload)

        for reason in decision.get("risk_flags", []):
            if reason in {
                "reconciliation_unhealthy",
                "missing_dynamic_fees",
                "missing_target_asset_identity",
                "insufficient_wallet_balance",
                "signer_unavailable",
                "invalid_market_data",
                "budget_cap_exceeded",
                "regime_dead",
                "liquidity_below_threshold",
            }:
                self.storage.log_pause_reason(reason, {"collection": market.collection_slug, "decision": decision})

        self.storage.log_decision(market.collection_slug, decision)
        return decision
