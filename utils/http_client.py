"""
utils/http_client.py
====================
Shared async HTTP client with:
  - In-memory TTL cache (avoids hammering free API rate limits)
  - Automatic retry with exponential backoff
  - 429 rate-limit handling
"""

from __future__ import annotations
import hashlib
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, ttl_seconds: int = settings.cache_ttl_seconds):
        self._store: dict[str, tuple[Any, datetime]] = {}
        self.ttl = timedelta(seconds=ttl_seconds)

    def _key(self, url: str, params: dict) -> str:
        raw = url + json.dumps(params, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, url: str, params: dict = {}) -> Optional[Any]:
        k = self._key(url, params)
        if k in self._store:
            value, cached_at = self._store[k]
            if datetime.utcnow() - cached_at < self.ttl:
                logger.debug("Cache HIT: %s", url)
                return value
            del self._store[k]
        return None

    def set(self, url: str, params: dict = {}, value: Any = None) -> None:
        self._store[self._key(url, params)] = (value, datetime.utcnow())

    def invalidate(self, url: str, params: dict = {}) -> None:
        k = self._key(url, params)
        self._store.pop(k, None)


# Module-level shared cache
cache = TTLCache()


class AsyncHTTPClient:
    """
    Thin async wrapper around httpx.
    Inject base_url and default headers per data source.
    """

    def __init__(
        self,
        base_url: str = "",
        headers: dict[str, str] = {},
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url
        self._headers = headers
        self._timeout = timeout

    async def get(
        self,
        endpoint: str,
        params: dict = {},
        extra_headers: dict = {},
        use_cache: bool = True,
        retries: int = 3,
    ) -> Any:
        url = self.base_url + endpoint
        merged_headers = {**self._headers, **extra_headers}

        if use_cache:
            cached = cache.get(url, params)
            if cached is not None:
                return cached

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(url, params=params, headers=merged_headers)
                    resp.raise_for_status()
                    data = resp.json()
                    if use_cache:
                        cache.set(url, params, data)
                    return data

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                logger.warning("HTTP %s on %s (attempt %d/%d)", status, url, attempt + 1, retries)
                if status == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning("Network error on %s (attempt %d/%d): %s", url, attempt + 1, retries, exc)
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

        raise RuntimeError(f"All {retries} attempts failed for {url}")
