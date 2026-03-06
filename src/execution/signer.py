from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:  # pragma: no cover
    Account = None
    encode_defunct = None


@dataclass
class SignResult:
    payload: dict[str, Any]
    signature: str


class Signer:
    def __init__(self, private_key: str | None) -> None:
        self.private_key = private_key

    def sign_order_payload(self, payload: dict[str, Any]) -> SignResult:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if self.private_key and Account is not None and encode_defunct is not None:
            signed = Account.sign_message(encode_defunct(hexstr=digest), private_key=self.private_key)
            signature = signed.signature.hex()
        else:
            signature = f"drysig_{digest}"
        return SignResult(payload=payload, signature=signature)
