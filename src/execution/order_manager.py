from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.client.opensea_client import OpenSeaClient
from src.execution.signer import Signer
from src.storage.storage import Storage

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    mode: str
    dry_run: bool
    write_enabled: bool


class OrderManager:
    def __init__(self, client: OpenSeaClient, signer: Signer, storage: Storage, cfg: ExecutionConfig) -> None:
        self.client = client
        self.signer = signer
        self.storage = storage
        self.cfg = cfg

    def _can_write(self) -> bool:
        return self.cfg.mode == "live" and self.cfg.write_enabled and not self.cfg.dry_run

    def build_offer_payload(self, collection_slug: str, price_eth: float, wallet: str) -> dict[str, Any]:
        return {
            "collection": collection_slug,
            "price_eth": round(price_eth, 6),
            "maker": wallet,
            "side": "offer",
        }

    def build_listing_payload(self, token_id: str, collection_slug: str, price_eth: float, wallet: str) -> dict[str, Any]:
        return {
            "token_id": token_id,
            "collection": collection_slug,
            "price_eth": round(price_eth, 6),
            "maker": wallet,
            "side": "listing",
        }

    def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        signed = self.signer.sign_order_payload(payload)
        order = {**signed.payload, "signature": signed.signature}
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{signed.signature[-10:]}"}
        else:
            result = self.client.create_item_offer(order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def create_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        signed = self.signer.sign_order_payload(payload)
        order = {**signed.payload, "signature": signed.signature}
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{signed.signature[-10:]}"}
        else:
            result = self.client.create_listing(order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def cancel_order(self, order_hash: str) -> dict[str, Any]:
        if not self._can_write():
            result = {"status": "DRY_RUN_CANCELLED", "order_hash": order_hash}
        else:
            result = self.client.cancel_order(order_hash)
        self.storage.upsert_order(order_hash, result.get("status", "CANCELLED"), result)
        return result
