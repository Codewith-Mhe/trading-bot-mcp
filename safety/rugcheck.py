"""
safety/rugcheck.py
===================
RugCheck API — Solana-specific token safety checks.
Free: https://rugcheck.xyz
Used when chain = "solana"

Checks: mint authority, freeze authority, LP concentration,
top holder %, creator wallet history, and metadata mutability.
"""

from __future__ import annotations
import logging
from utils.http_client import AsyncHTTPClient

logger = logging.getLogger(__name__)

_client = AsyncHTTPClient(base_url="https://api.rugcheck.xyz/v1")


async def scan_rugcheck(mint_address: str) -> dict:
    """
    Run RugCheck scan on a Solana token mint address.
    Returns raw risk data. Used as supplementary data for Solana tokens.
    """
    try:
        raw = await _client.get(f"/tokens/{mint_address}/report", use_cache=False)

        risks = raw.get("risks", [])
        score = raw.get("score", 0)

        # Normalize risk list into plain strings
        risk_labels = [r.get("name", r) if isinstance(r, dict) else str(r) for r in risks]

        return {
            "mint_address": mint_address,
            "score": score,
            "risk_level": raw.get("score_normalised", "unknown"),
            "risks": risk_labels,
            "mint_authority_disabled": raw.get("mintAuthority") is None,
            "freeze_authority_disabled": raw.get("freezeAuthority") is None,
            "top_10_holder_pct": raw.get("topHolders", {}).get("pct", 0),
            "lp_locked": raw.get("markets", [{}])[0].get("lp", {}).get("lpLocked", False)
            if raw.get("markets") else False,
            "raw": raw,
            "source": "rugcheck",
        }

    except Exception as exc:
        logger.error("RugCheck failed for %s: %s", mint_address[:10], exc)
        return {"mint_address": mint_address, "error": str(exc), "source": "rugcheck"}
