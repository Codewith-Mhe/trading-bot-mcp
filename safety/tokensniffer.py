"""
safety/tokensniffer.py
=======================
TokenSniffer API — pattern-based clone and scam detection.
Score: 0-100. Higher = safer. Detects known scam patterns and clones.
Requires API key: https://tokensniffer.com ($100-200/month)

Set TOKENSNIFFER_API_KEY in your .env file.
Falls back gracefully to a neutral score (50/100) if no key is set,
so GoPlus + Honeypot.is still gate trades correctly without it.
"""

from __future__ import annotations
import logging
from utils.http_client import AsyncHTTPClient
from models.safety_schemas import TokenSnifferResult
from config.settings import settings

logger = logging.getLogger(__name__)

_CHAIN_SLUGS: dict[str, str] = {
    "ethereum": "eth",   "eth": "eth",
    "base": "base",
    "arbitrum": "arb",   "arb": "arb",
    "bsc": "bsc",
    "polygon": "polygon", "matic": "polygon",
    "optimism": "optimism", "op": "optimism",
}


def _get_client() -> AsyncHTTPClient:
    """Build client with API key from settings (loaded from .env)."""
    key = settings.tokensniffer_api_key
    headers = {"X-API-Key": key} if key else {}
    return AsyncHTTPClient(base_url="https://tokensniffer.com/api/v2", headers=headers)


async def scan_tokensniffer(contract_address: str, chain: str = "ethereum") -> TokenSnifferResult:
    """
    Run TokenSniffer pattern scan.
    Returns TokenSnifferResult with score (0-100) and clone/scam flags.
    Silently skips and returns neutral score if no API key is configured.
    """
    if not settings.tokensniffer_api_key:
        logger.debug("TOKENSNIFFER_API_KEY not set — returning neutral score")
        return TokenSnifferResult(score=50, raw={"skipped": "no_api_key"})

    chain_slug = _CHAIN_SLUGS.get(chain.lower(), "eth")
    client = _get_client()

    try:
        raw = await client.get(
            f"/tokens/{chain_slug}/{contract_address}",
            params={"allow_cached_results": True, "include_metrics": True},
            use_cache=False,
        )

        score = int(raw.get("score", 50) or 50)
        similar = raw.get("similar_tokens") or []

        return TokenSnifferResult(
            score=score,
            similar_tokens=len(similar),
            is_copy=len(similar) > 0,
            deployer_previous_scams=int(raw.get("deployer_scam_count") or 0),
            raw=raw,
        )

    except Exception as exc:
        logger.error("TokenSniffer failed for %s: %s", contract_address[:10], exc)
        return TokenSnifferResult(score=50, raw={"error": str(exc)})
