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
        required = {"chain", "protocol", "parameters", "eip712"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"invalid_order_payload_missing={sorted(missing)}")
        eip712 = payload.get("eip712", {})
        if not isinstance(eip712, dict) or any(k not in eip712 for k in ("domain", "types", "message")):
            raise ValueError("invalid_order_payload_missing_eip712_fields")

    def sign_order_payload(self, payload: dict[str, Any]) -> SignResult:
        self._validate_order_payload(payload)

        if not self.private_key or Account is None or encode_typed_data is None:
            raise ValueError("live_signing_unavailable_private_key_or_eth_account_missing")

        signable = encode_typed_data(
            domain_data=payload["eip712"]["domain"],
            message_types=payload["eip712"]["types"],
            message_data=payload["eip712"]["message"],
        )
        signature = Account.sign_message(signable, private_key=self.private_key).signature.hex()
        return SignResult(payload=payload, signature=signature)
