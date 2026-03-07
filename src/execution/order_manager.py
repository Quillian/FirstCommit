from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass

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

    @staticmethod
    def _wei(eth: float) -> str:
        return str(int(round(float(eth) * 10**18)))

    @staticmethod
    def _random_salt() -> str:
        return str(random.getrandbits(256))

    @staticmethod
    def _chain_id(chain: str) -> int:
        return {"ethereum": 1, "polygon": 137}.get(chain, 1)

    def _dry_signature(self, payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return f"drysig_{hashlib.sha256(canonical).hexdigest()}"

    def _seaport_order_shell(self, side: str, wallet: str, payload: dict[str, object]) -> dict[str, object]:
        if payload.get("price_eth", 0) <= 0:
            raise ValueError("invalid_order_payload_price")

        now = int(time.time())
        end = now + 3600
        price_wei = self._wei(float(payload["price_eth"]))
        collection = str(payload.get("collection", ""))
        token_id = str(payload.get("token_id", "0"))
        collection_contract = str(payload.get("collection_contract", "")).strip()
        wrapped_native = str(payload.get("payment_token", "")).strip()
        if not collection_contract or collection_contract == "0x0000000000000000000000000000000000000000":
            raise ValueError("invalid_order_payload_collection_contract")
        if not wrapped_native or wrapped_native == "0x0000000000000000000000000000000000000000":
            raise ValueError("invalid_order_payload_payment_token")

        offer_item = {
            "itemType": 1,
            "token": wrapped_native,
            "identifierOrCriteria": "0",
            "startAmount": price_wei,
            "endAmount": price_wei,
        }
        consideration_item = {
            "itemType": 2,
            "token": collection_contract,
            "identifierOrCriteria": token_id,
            "startAmount": "1",
            "endAmount": "1",
            "recipient": wallet,
        }

        if side == "listing":
            offer_item = {
                "itemType": 2,
                "token": collection_contract,
                "identifierOrCriteria": token_id,
                "startAmount": "1",
                "endAmount": "1",
            }
            consideration_item = {
                "itemType": 1,
                "token": wrapped_native,
                "identifierOrCriteria": "0",
                "startAmount": price_wei,
                "endAmount": price_wei,
                "recipient": wallet,
            }

        return {
            "chain": self.cfg.chain,
            "protocol": self.cfg.protocol,
            "chain_id": self._chain_id(self.cfg.chain),
            "side": side,
            "collection_slug": collection,
            "protocol_data": {
                "parameters": {
                    "offerer": wallet,
                    "zone": "0x0000000000000000000000000000000000000000",
                    "offer": [offer_item],
                    "consideration": [consideration_item],
                    "orderType": 0,
                    "startTime": str(now),
                    "endTime": str(end),
                    "zoneHash": "0x" + "00" * 32,
                    "salt": self._random_salt(),
                    "conduitKey": "0x" + "00" * 32,
                    "counter": "0",
                }
            },
        }

    def build_offer_payload(
        self,
        collection_slug: str,
        price_eth: float,
        wallet: str,
        collection_contract: str,
        payment_token: str,
    ) -> dict[str, object]:
        return self._seaport_order_shell(
            "offer",
            wallet,
            {
                "collection": collection_slug,
                "price_eth": price_eth,
                "collection_contract": collection_contract,
                "payment_token": payment_token,
            },
        )

    def build_listing_payload(
        self,
        token_id: str,
        collection_slug: str,
        price_eth: float,
        wallet: str,
        collection_contract: str,
        payment_token: str,
    ) -> dict[str, object]:
        return self._seaport_order_shell(
            "listing",
            wallet,
            {
                "token_id": token_id,
                "collection": collection_slug,
                "price_eth": price_eth,
                "collection_contract": collection_contract,
                "payment_token": payment_token,
            },
        )

    def _attach_signature(self, payload: dict[str, object]) -> dict[str, object]:
        if self._can_write():
            signed = self.signer.sign_order_payload(payload)
            return {**signed.payload, "signature": signed.signature}
        self.signer._validate_order_payload(payload)
        return {**payload, "signature": self._dry_signature(payload)}

    def create_offer(self, payload: dict[str, object]) -> dict[str, object]:
        order = self._attach_signature(payload)
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{order['signature'][-10:]}"}
        else:
            result = self.client.create_item_offer(self.cfg.chain, self.cfg.protocol, order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def create_listing(self, payload: dict[str, object]) -> dict[str, object]:
        order = self._attach_signature(payload)
        if not self._can_write():
            result = {"status": "DRY_RUN", "order": order, "order_hash": f"dry_{order['signature'][-10:]}"}
        else:
            result = self.client.create_listing(self.cfg.chain, self.cfg.protocol, order)
        self.storage.upsert_order(result.get("order_hash", "unknown"), result.get("status", "PENDING"), result)
        return result

    def cancel_order(self, order_hash: str) -> dict[str, object]:
        if not self._can_write():
            result = {"status": "DRY_RUN_CANCELLED", "order_hash": order_hash}
        else:
            result = self.client.cancel_order(self.cfg.chain, self.cfg.protocol, order_hash)
        self.storage.upsert_order(order_hash, result.get("status", "CANCELLED"), result)
        return result
