"""
safety/goplus.py
=================
GoPlus Security API — instant on-chain risk flags.
Free tier: https://gopluslabs.io

Checks: honeypot, mint function, blacklist, pause, proxy,
hidden owner, buy/sell tax, LP lock, holder concentration.
Typical response time: 1-2 seconds.
"""

from __future__ import annotations
import logging
from utils.http_client import AsyncHTTPClient
from models.safety_schemas import GoPlusResult

logger = logging.getLogger(__name__)

# GoPlus chain ID mapping
_CHAIN_IDS: dict[str, str] = {
    "ethereum": "1",  "eth": "1",
    "base": "8453",
    "arbitrum": "42161",  "arb": "42161",
    "bsc": "56",
    "polygon": "137",  "matic": "137",
    "optimism": "10",  "op": "10",
    "solana": "solana",  "sol": "solana",
    "avalanche": "43114",  "avax": "43114",
}

_client = AsyncHTTPClient(base_url="https://api.gopluslabs.io/api/v1")


async def scan_goplus(contract_address: str, chain: str = "ethereum") -> GoPlusResult:
    """Run GoPlus security scan. Returns normalized GoPlusResult."""
    chain_id = _CHAIN_IDS.get(chain.lower(), "1")
    ca = contract_address.lower()

    try:
        if chain_id == "solana":
            raw = await _client.get(
                "/solana/token_security",
                params={"contract_addresses": ca},
                use_cache=False,
            )
        else:
            raw = await _client.get(
                f"/token_security/{chain_id}",
                params={"contract_addresses": ca},
                use_cache=False,
            )

        token_data: dict = (raw.get("result") or {}).get(ca, {})
        if not token_data:
            logger.warning("GoPlus: no data for %s on %s", ca[:10], chain)
            return GoPlusResult(raw=raw)

        def _f(k: str) -> float:
            try:
                return float(token_data.get(k) or 0)
            except (ValueError, TypeError):
                return 0.0

        def _b(k: str) -> bool:
            return str(token_data.get(k, "0")).strip() in ("1", "true", "True")

        return GoPlusResult(
            is_honeypot=_b("is_honeypot"),
            has_mint_function=_b("is_mintable"),
            has_blacklist=_b("is_blacklisted"),
            has_pause_function=_b("transfer_pausable"),
            is_proxy=_b("is_proxy"),
            has_hidden_owner=_b("hidden_owner"),
            buy_tax_pct=_f("buy_tax") * 100,
            sell_tax_pct=_f("sell_tax") * 100,
            lp_locked_pct=_f("lp_locked_percent"),
            top_10_holder_pct=_f("holder_percent") * 100,
            creator_balance_pct=_f("creator_percent") * 100,
            is_open_source=_b("is_open_source"),
            trading_cooldown=_b("trading_cooldown"),
            transfer_pausable=_b("transfer_pausable"),
            raw=token_data,
        )

    except Exception as exc:
        logger.error("GoPlus failed for %s: %s", ca[:10], exc)
        return GoPlusResult(raw={"error": str(exc)})
