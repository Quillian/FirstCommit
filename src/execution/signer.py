from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from eth_account import Account
    from eth_account.messages import encode_typed_data
except ImportError:  # pragma: no cover
    Account = None
    encode_typed_data = None


@dataclass
class SignResult:
    payload: dict[str, Any]
    signature: str


class Signer:
    def __init__(self, private_key: str | None) -> None:
        self.private_key = private_key

    @staticmethod
    def _validate_order_payload(payload: dict[str, Any]) -> None:
        required = {"chain", "protocol", "protocol_data"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"invalid_order_payload_missing={sorted(missing)}")

        protocol_data = payload.get("protocol_data", {})
        if not isinstance(protocol_data, dict) or "parameters" not in protocol_data:
            raise ValueError("invalid_order_payload_missing_protocol_data")

        params = protocol_data.get("parameters") or {}
        required_params = {
            "offerer",
            "offer",
            "consideration",
            "orderType",
            "startTime",
            "endTime",
            "zone",
            "zoneHash",
            "salt",
            "conduitKey",
            "counter",
        }
        missing_params = required_params - params.keys()
        if missing_params:
            raise ValueError(f"invalid_order_payload_missing_parameters={sorted(missing_params)}")

    @staticmethod
    def _seaport_typed_data(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        params = payload["protocol_data"]["parameters"]
        domain = {
            "name": "Seaport",
            "version": "1.6",
            "chainId": int(payload.get("chain_id", 1)),
            "verifyingContract": payload.get("seaport_contract", "0x0000000000000068F116a894984e2DB1123eB395"),
        }
        types = {
            "OfferItem": [
                {"name": "itemType", "type": "uint8"},
                {"name": "token", "type": "address"},
                {"name": "identifierOrCriteria", "type": "uint256"},
                {"name": "startAmount", "type": "uint256"},
                {"name": "endAmount", "type": "uint256"},
            ],
            "ConsiderationItem": [
                {"name": "itemType", "type": "uint8"},
                {"name": "token", "type": "address"},
                {"name": "identifierOrCriteria", "type": "uint256"},
                {"name": "startAmount", "type": "uint256"},
                {"name": "endAmount", "type": "uint256"},
                {"name": "recipient", "type": "address"},
            ],
            "OrderComponents": [
                {"name": "offerer", "type": "address"},
                {"name": "zone", "type": "address"},
                {"name": "offer", "type": "OfferItem[]"},
                {"name": "consideration", "type": "ConsiderationItem[]"},
                {"name": "orderType", "type": "uint8"},
                {"name": "startTime", "type": "uint256"},
                {"name": "endTime", "type": "uint256"},
                {"name": "zoneHash", "type": "bytes32"},
                {"name": "salt", "type": "uint256"},
                {"name": "conduitKey", "type": "bytes32"},
                {"name": "counter", "type": "uint256"},
            ],
        }
        return domain, types, params

    def sign_order_payload(self, payload: dict[str, Any]) -> SignResult:
        self._validate_order_payload(payload)
        if not self.private_key or Account is None or encode_typed_data is None:
            raise ValueError("live_signing_unavailable_private_key_or_eth_account_missing")

        domain, types, message = self._seaport_typed_data(payload)
        signable = encode_typed_data(
            domain_data=domain,
            message_types=types,
            message_data=message,
        )
        signature = Account.sign_message(signable, private_key=self.private_key).signature.hex()
        return SignResult(payload=payload, signature=signature)
