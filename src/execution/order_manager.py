from __future__ import annotations

import hashlib
import json
import logging
import random
import time
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

    @staticmethod
    def _fee_amount_wei(price_wei: int, bps: int) -> int:
        return int((price_wei * max(bps, 0)) / 10_000)

    def _seaport_order_shell(
        self,
        side: str,
        wallet: str,
        payload: dict[str, Any],
        fee_recipients: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        if payload.get("price_eth", 0) <= 0:
            raise ValueError("invalid_order_payload_price")

        now = int(time.time())
        end = now + 3600
        price_wei = int(self._wei(float(payload["price_eth"])))
        collection = str(payload.get("collection", ""))
        token_id = str(payload.get("token_id", "0"))
        collection_contract = str(payload.get("collection_contract", "0x0000000000000000000000000000000000000000"))
        wrapped_native = str(payload.get("payment_token", "0x0000000000000000000000000000000000000000"))

        offer_item = {
            "itemType": 1,
            "token": wrapped_native,
            "identifierOrCriteria": "0",
            "startAmount": str(price_wei),
            "endAmount": str(price_wei),
        }
        fee_recipients = fee_recipients or []
        fee_items: list[dict[str, str]] = []
        total_fee_wei = 0
        for fee in fee_recipients:
            recipient = str(fee.get("recipient", "")).strip()
            bps = int(fee.get("bps", 0))
            if not recipient or bps <= 0:
                continue
            fee_amount = self._fee_amount_wei(price_wei, bps)
            if fee_amount <= 0:
                continue
            total_fee_wei += fee_amount
            fee_items.append(
                {
                    "itemType": 1,
                    "token": wrapped_native,
                    "identifierOrCriteria": "0",
                    "startAmount": str(fee_amount),
                    "endAmount": str(fee_amount),
                    "recipient": recipient,
                }
            )

        seller_proceeds_wei = max(price_wei - total_fee_wei, 0)

        consideration: list[dict[str, str]] = [
            {
                "itemType": 2,
                "token": collection_contract,
                "identifierOrCriteria": token_id,
                "startAmount": "1",
                "endAmount": "1",
                "recipient": wallet,
            }
        ]

        if side == "listing":
            offer_item = {
                "itemType": 2,
                "token": collection_contract,
                "identifierOrCriteria": token_id,
                "startAmount": "1",
                "endAmount": "1",
            }
            consideration = [
                {
                    "itemType": 1,
                    "token": wrapped_native,
                    "identifierOrCriteria": "0",
                    "startAmount": str(seller_proceeds_wei),
                    "endAmount": str(seller_proceeds_wei),
                    "recipient": wallet,
                },
                *fee_items,
            ]
        else:
            if seller_proceeds_wei > 0:
                consideration.append(
                    {
                        "itemType": 1,
                        "token": wrapped_native,
                        "identifierOrCriteria": "0",
                        "startAmount": str(seller_proceeds_wei),
                        "endAmount": str(seller_proceeds_wei),
                        "recipient": str(payload.get("seller_recipient", wallet)),
                    }
                )
            consideration.extend(fee_items)

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
                    "consideration": consideration,
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
        fee_recipients: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        return self._seaport_order_shell(
            "offer",
            wallet,
            {
                "collection": collection_slug,
                "price_eth": price_eth,
            },
            fee_recipients=fee_recipients,
        )

    def build_listing_payload(
        self,
        token_id: str,
        collection_slug: str,
        price_eth: float,
        wallet: str,
        fee_recipients: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        return self._seaport_order_shell(
            "listing",
            wallet,
            {
                "token_id": token_id,
                "collection": collection_slug,
                "price_eth": price_eth,
            },
            fee_recipients=fee_recipients,
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
