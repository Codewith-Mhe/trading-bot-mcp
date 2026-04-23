"""
safety/honeypot.py
===================
Honeypot.is — simulate a sell before buying.
Free, no API key required: https://honeypot.is

This actually simulates the buy AND sell transaction on-chain
to detect tokens that let you buy but not sell.
Typical response time: 0.5-1 second.
"""

from __future__ import annotations
import logging
from utils.http_client import AsyncHTTPClient
from models.safety_schemas import HoneypotResult

logger = logging.getLogger(__name__)

# Honeypot.is chain IDs
_CHAIN_IDS: dict[str, int] = {
    "ethereum": 1,   "eth": 1,
    "base": 8453,
    "arbitrum": 42161,  "arb": 42161,
    "bsc": 56,
    "polygon": 137,  "matic": 137,
    "optimism": 10,  "op": 10,
    "avalanche": 43114,  "avax": 43114,
}

_client = AsyncHTTPClient(base_url="https://api.honeypot.is/v2")


async def scan_honeypot(contract_address: str, chain: str = "ethereum") -> HoneypotResult:
    """
    Simulate buy + sell for a token contract.
    Returns HoneypotResult with is_honeypot flag and tax percentages.
    """
    chain_id = _CHAIN_IDS.get(chain.lower(), 1)

    try:
        raw = await _client.get(
            "/IsHoneypot",
            params={
                "address": contract_address,
                "chainID": chain_id,
            },
            use_cache=False,
        )

        sim = raw.get("simulationResult", {})
        hp = raw.get("honeypotResult", {})
        token = raw.get("token", {})

        def _f(val) -> float:
            try:
                return float(val or 0) * 100
            except (ValueError, TypeError):
                return 0.0

        is_hp = hp.get("isHoneypot", False)
        reason = hp.get("honeypotReason") if is_hp else None

        result = HoneypotResult(
            is_honeypot=is_hp,
            simulation_success=sim.get("success", False),
            buy_tax_pct=_f(sim.get("buyTax")),
            sell_tax_pct=_f(sim.get("sellTax")),
            transfer_tax_pct=_f(sim.get("transferTax")),
            buy_gas=sim.get("buyGas"),
            sell_gas=sim.get("sellGas"),
            reason=reason,
            raw=raw,
        )

        if is_hp:
            logger.warning(
                "🍯 HONEYPOT detected: %s on %s — %s",
                contract_address[:10], chain, reason or "unknown reason"
            )

        return result

    except Exception as exc:
        logger.error("Honeypot.is failed for %s: %s", contract_address[:10], exc)
        return HoneypotResult(raw={"error": str(exc)})
