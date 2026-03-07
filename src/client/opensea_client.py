from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.client.auth import OpenSeaAuth
from src.client.rate_limiter import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)


class OpenSeaClientError(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, message: str) -> None:
        super().__init__(f"OpenSea {method} {path} failed status={status} message={message}")
        self.method = method
        self.path = path
        self.status = status
        self.message = message


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

    @staticmethod
    def _is_retryable_http(status: int) -> bool:
        return status == 429 or 500 <= status < 600

    @staticmethod
    def _retry_delay_sec(attempt: int) -> float:
        return min(0.5 * (2 ** (attempt - 1)), 8.0)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.rate_limiter.wait()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        query_string = f"?{urlencode(query)}" if query else ""
        url = f"{self.base_url}{path}{query_string}"
        last_error: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                req = Request(url, data=body, method=method)
                for k, v in self.auth.headers().items():
                    req.add_header(k, v)
                if payload is not None:
                    req.add_header("Content-Type", "application/json")
                with urlopen(req, timeout=self.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                logger.warning(
                    "OpenSea API HTTP error attempt=%s method=%s path=%s status=%s body=%s",
                    attempt,
                    method,
                    path,
                    exc.code,
                    err_body,
                )
                last_error = OpenSeaClientError(method, path, exc.code, err_body)
                if attempt < self.retry_attempts and self._is_retryable_http(exc.code):
                    time.sleep(self._retry_delay_sec(attempt))
                    continue
                raise last_error
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                logger.warning("OpenSea API transport error attempt=%s method=%s path=%s err=%s", attempt, method, path, exc)
                last_error = exc
                if attempt < self.retry_attempts:
                    time.sleep(self._retry_delay_sec(attempt))
                    continue
                raise OpenSeaClientError(method, path, None, str(last_error)) from exc

        raise OpenSeaClientError(method, path, None, str(last_error))

    def get_collection_details(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/collections/{slug}")

    def get_collection_stats(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/collections/{slug}/stats")

    def get_events_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/events/collection/{slug}", query={"event_type": "sale"})

    def get_best_listings_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/listings/collection/{slug}/best")

    def get_all_listings_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/listings/collection/{slug}/all")

    def get_all_offers_by_collection(self, slug: str) -> Dict[str, Any]:
        return self._request("GET", f"/offers/collection/{slug}/all")

    def get_account_nfts(self, chain: str, address: str) -> Dict[str, Any]:
        return self._request("GET", f"/chain/{chain}/account/{address}/nfts")

    def create_item_offer(self, chain: str, protocol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", f"/orders/{chain}/{protocol}/offers", payload)

    def create_listing(self, chain: str, protocol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", f"/orders/{chain}/{protocol}/listings", payload)

    def cancel_order(self, chain: str, protocol: str, order_hash: str) -> Dict[str, Any]:
        return self._request("POST", f"/orders/{chain}/{protocol}/{order_hash}/cancel", payload={})

    def fulfill_listing(self, payload: Dict[str, Any], chain: str, protocol: str) -> Dict[str, Any]:
        return self._request("POST", "/api/v2/listings/fulfillment_data", payload)

    def fulfill_offer(self, payload: Dict[str, Any], chain: str, protocol: str) -> Dict[str, Any]:
        return self._request("POST", "/api/v2/offers/fulfillment_data", payload)

    def stream_integration_path(self) -> str:
        return "Use configured stream websocket URL with auth headers for future event-driven fills/listing deltas"
