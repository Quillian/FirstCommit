from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class AuthConfig:
    api_key_env: str


class OpenSeaAuth:
    def __init__(self, cfg: AuthConfig) -> None:
        self.cfg = cfg

    def headers(self) -> Dict[str, str]:
        api_key = os.getenv(self.cfg.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"Missing OpenSea API key in env var {self.cfg.api_key_env}")
        return {
            "accept": "application/json",
            "x-api-key": api_key,
            "content-type": "application/json",
        }
