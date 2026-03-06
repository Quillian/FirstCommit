from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.client.auth import OpenSeaAuth
from src.client.rate_limiter import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)


class OpenSeaClient:
    def __init__(
        self,
        base_url: str,
        auth: OpenSeaAuth,
        rate_limiter: SlidingWindowRateLimiter,
        timeout_sec: int = 10,
        retry_attempts: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.rate_limiter = rate_limiter
        self.timeout_sec = timeout_sec
        self.retry_attempts = retry_attempts

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.rate_limiter.wait()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                req = Request(f"{self.base_url}{path}", data=body, method=method)
                for k, v in self.auth.headers().items():
                    req.add_header(k, v)
                with urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("OpenSea API error attempt=%s path=%s err=%s", attempt, path, exc)
                if attempt < self.retry_attempts:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"OpenSea request failed: {path} - {last_error}")

    def get_collection_details(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/collections/{slug}")

    def get_collection_stats(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/collections/{slug}/stats")

    def get_events_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/events/collection/{slug}")

    def get_best_listings_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/listings/collection/{slug}/best")

    def get_all_listings_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/listings/collection/{slug}/all")

    def get_all_offers_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/offers/collection/{slug}/all")

    def create_item_offer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/offers", payload)

    def create_listing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/listings", payload)

    def cancel_order(self, order_hash: str) -> Dict[str, Any]:
        return self._request("POST", f"/orders/{order_hash}/cancel")

    def fulfill_listing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/fulfillment_data/listings", payload)

    def fulfill_offer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/fulfillment_data/offers", payload)

    def stream_integration_path(self) -> str:
        return "Use configured stream websocket URL with auth headers for future event-driven fills/listing deltas"
