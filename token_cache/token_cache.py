"""
utils/token_cache.py
=====================
Dedicated token-level cache for safety scan results.
Keyed by contract address. TTL: 5 minutes per token.

Why separate from the HTTP cache:
- Safety scans are expensive (3 API calls in parallel)
- Re-scanning the same CA within 5 minutes wastes time and API quota
- The CA is the key — not the URL — so HTTP-level caching doesn't help here
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

TOKEN_CACHE_TTL_MINUTES = 5


@dataclass
class CachedTokenScan:
    contract_address: str
    chain: str
    safety_score: int
    is_honeypot: bool
    warnings: list[str]
    raw_goplus: dict
    raw_tokensniffer: dict
    raw_honeypot: dict
    scanned_at: datetime = field(default_factory=datetime.utcnow)

    def is_fresh(self) -> bool:
        return datetime.utcnow() - self.scanned_at < timedelta(minutes=TOKEN_CACHE_TTL_MINUTES)

    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.scanned_at).total_seconds()


class TokenCache:
    """
    In-memory cache for token safety scan results.
    Key: f"{chain}:{contract_address.lower()}"
    """

    def __init__(self) -> None:
        self._store: dict[str, CachedTokenScan] = {}

    def _key(self, chain: str, contract_address: str) -> str:
        return f"{chain.lower()}:{contract_address.lower()}"

    def get(self, chain: str, contract_address: str) -> Optional[CachedTokenScan]:
        k = self._key(chain, contract_address)
        entry = self._store.get(k)
        if entry and entry.is_fresh():
            logger.debug(
                "Token cache HIT: %s on %s (age: %.0fs)",
                contract_address[:10], chain, entry.age_seconds()
            )
            return entry
        if entry:
            # Stale — remove it
            del self._store[k]
        return None

    def set(self, scan: CachedTokenScan) -> None:
        k = self._key(scan.chain, scan.contract_address)
        self._store[k] = scan
        logger.debug("Token cache SET: %s on %s", scan.contract_address[:10], scan.chain)

    def invalidate(self, chain: str, contract_address: str) -> None:
        k = self._key(chain, contract_address)
        self._store.pop(k, None)

    def size(self) -> int:
        return len(self._store)

    def clear_stale(self) -> int:
        """Remove expired entries. Returns count removed."""
        stale = [k for k, v in self._store.items() if not v.is_fresh()]
        for k in stale:
            del self._store[k]
        return len(stale)


# Module-level shared instance
token_cache = TokenCache()
