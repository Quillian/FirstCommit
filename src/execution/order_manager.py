from __future__ import annotations

import hashlib
import json
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
    chain: str
    protocol: str


class OrderManager:
    def __init__(self, client: OpenSeaClient, signer: Signer, storage: Storage, cfg: ExecutionConfig) -> None:
        self.client = client
        self.signer = signer
        self.storage = storage
        self.cfg = cfg

    def _can_write(self) -> bool:
        return self.cfg.mode == "live" and self.cfg.write_enabled and not self.cfg.dry_run

    def _dry_signature(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return f"drysig_{hashlib.sha256(canonical).hexdigest()}"

    def _seaport_order_shell(self, side: str, wallet: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("price_eth", 0) <= 0:
            raise ValueError("invalid_order_payload_price")
        return {
            "chain": self.cfg.chain,
            "protocol": self.cfg.protocol,
            "side": side,
            "maker": wallet,
            "parameters": {
                "collection": payload.get("collection"),
                "token_id": payload.get("token_id"),
                "price_eth": round(float(payload["price_eth"]), 6),
                "quantity": 1,
            },
            # this structure mirrors Seaport typed-signing flow and is signed in live mode
            "eip712": {
                "domain": {
                    "name": "Seaport",
                    "version": "1.6",
                    "chainId": 1,
                    "verifyingContract": "0x0000000000000068F116a894984e2DB1123eB395",
                },
                "types": {
                    "OrderComponents": [
                        {"name": "maker", "type": "address"},
                        {"name": "side", "type": "string"},
                        {"name": "price", "type": "string"},
                        {"name": "collection", "type": "string"},
                        {"name": "tokenId", "type": "string"},
                    ]
                },
                "message": {
                    "maker": wallet,
                    "side": side,
                    "price": str(round(float(payload["price_eth"]), 6)),
                    "collection": payload.get("collection", ""),
                    "tokenId": str(payload.get("token_id", "")),
                },
            },
        }

    def build_offer_payload(self, collection_slug: str, price_eth: float, wallet: str) -> dict[str, Any]:
        return self._seaport_order_shell(
            "offer",
            wallet,
            {
                "collection": collection_slug,
                "price_eth": price_eth,
            },
        )

    def build_listing_payload(self, token_id: str, collection_slug: str, price_eth: float, wallet: str) -> dict[str, Any]:
        return self._seaport_order_shell(
            "listing",
            wallet,
            {
                "token_id": token_id,
                "collection": collection_slug,
                "price_eth": price_eth,
            },
        )

    def _attach_signature(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._can_write():
            signed = self.signer.sign_order_payload(payload)
            return {**signed.payload, "signature": signed.signature}
        # in paper/dry modes, we still enforce payload shape and generate deterministic fake sig
        self.signer._validate_order_payload(payload)
        return {**payload, "signature": self._dry_signature(payload)}

    def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        order = self._attach_signature(payload)
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{order['signature'][-10:]}"}
        else:
            result = self.client.create_item_offer(self.cfg.chain, self.cfg.protocol, order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def create_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        order = self._attach_signature(payload)
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{order['signature'][-10:]}"}
        else:
            result = self.client.create_listing(self.cfg.chain, self.cfg.protocol, order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def cancel_order(self, order_hash: str) -> dict[str, Any]:
        if not self._can_write():
            result = {"status": "DRY_RUN_CANCELLED", "order_hash": order_hash}
        else:
            result = self.client.cancel_order(self.cfg.chain, self.cfg.protocol, order_hash)
        self.storage.upsert_order(order_hash, result.get("status", "CANCELLED"), result)
        return result
