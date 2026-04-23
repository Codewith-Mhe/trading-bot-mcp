"""
servers/dexscreener_server.py
==============================
DexScreener MCP tools — DEX pair data, prices, liquidity, new pairs.
No API key required.
"""

from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from models.schemas import DexPair
from utils.http_client import AsyncHTTPClient
from config.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("dexscreener")
_client = AsyncHTTPClient(base_url=settings.dexscreener_base_url)


# ── Helper ────────────────────────────────────────────────────────────────

def _parse_pair(p: dict) -> dict:
    base = p.get("baseToken", {})
    quote = p.get("quoteToken", {})
    pc = p.get("priceChange", {})
    txns = p.get("txns", {}).get("h24", {})
    return DexPair(
        pair_address=p.get("pairAddress", ""),
        base_token_symbol=base.get("symbol", ""),
        quote_token_symbol=quote.get("symbol", ""),
        price_usd=float(p.get("priceUsd") or 0),
        price_native=float(p.get("priceNative") or 0),
        liquidity_usd=p.get("liquidity", {}).get("usd"),
        volume_24h_usd=p.get("volume", {}).get("h24"),
        price_change_5m_pct=pc.get("m5"),
        price_change_1h_pct=pc.get("h1"),
        price_change_24h_pct=pc.get("h24"),
        txns_24h_buys=txns.get("buys"),
        txns_24h_sells=txns.get("sells"),
        dex_name=p.get("dexId"),
        chain=p.get("chainId"),
        fdv=p.get("fdv"),
    ).model_dump()


# ── Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_token_pairs(query: str, limit: int = 15) -> list[dict]:
    """
    Search for DEX trading pairs by token name or symbol across all chains.
    Returns price, liquidity depth, 24h volume, buy/sell transaction counts,
    and price change across 5min, 1hr, and 24hr windows.
    Results sorted by liquidity (highest first).
    Examples: 'PEPE', 'WBTC', 'ARB', 'OP', 'LINK', 'AAVE'.
    Use to discover where a token trades and assess its DEX liquidity.
    """
    data = await _client.get("/search", params={"q": query}, use_cache=False)
    pairs = sorted(
        data.get("pairs") or [],
        key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0,
        reverse=True,
    )
    return [_parse_pair(p) for p in pairs[:limit]]


@mcp.tool()
async def get_pair_by_address(chain: str, pair_address: str) -> list[dict]:
    """
    Fetch real-time data for a specific DEX pair by contract address.
    Chain options: 'ethereum', 'base', 'arbitrum', 'bsc', 'polygon', 'solana'.
    Use when you have a specific pair address from a trade signal or whale alert.
    """
    data = await _client.get(f"/pairs/{chain}/{pair_address}", use_cache=False)
    return [_parse_pair(p) for p in (data.get("pairs") or [])]


@mcp.tool()
async def get_token_all_pairs(chain: str, token_address: str) -> list[dict]:
    """
    Get all DEX pools/pairs for a specific token contract address on a given chain.
    Returns all venues where this token is traded, sorted by liquidity descending.
    Use before executing a trade to identify the best liquidity venue.
    Chain options: 'ethereum', 'base', 'arbitrum', 'bsc', 'polygon'.
    """
    data = await _client.get(f"/tokens/{chain}/{token_address}", use_cache=False)
    pairs = sorted(
        data.get("pairs") or [],
        key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0,
        reverse=True,
    )
    return [_parse_pair(p) for p in pairs[:10]]


@mcp.tool()
async def get_top_gainers(chain: str = "ethereum", min_liquidity: float = 10_000, limit: int = 10) -> list[dict]:
    """
    Find DEX pairs with the highest 24h price gains on a specific chain.
    Filters out dust pairs below the minimum liquidity threshold.
    Returns pairs sorted by 24h price change percentage (highest first).
    Use to identify momentum plays or trending tokens for Strategy Agent decisions.
    Chain options: 'ethereum', 'base', 'arbitrum', 'bsc', 'solana'.
    """
    data = await _client.get("/search", params={"q": chain}, use_cache=False)
    pairs = [
        p for p in (data.get("pairs") or [])
        if p.get("chainId", "").lower() == chain.lower()
        and p.get("priceChange", {}).get("h24") is not None
        and (p.get("liquidity", {}).get("usd") or 0) >= min_liquidity
    ]
    pairs.sort(key=lambda x: x.get("priceChange", {}).get("h24", 0) or 0, reverse=True)
    return [_parse_pair(p) for p in pairs[:limit]]


@mcp.tool()
async def get_new_pairs(chain: str = "ethereum", limit: int = 20) -> list[dict]:
    """
    Discover the most recently created DEX trading pairs on a given chain.
    Returns pairs sorted by creation timestamp (newest first), with initial
    liquidity, price, and early transaction activity.
    Use for early-stage token discovery or monitoring newly deployed pools.
    Chain options: 'ethereum', 'base', 'arbitrum', 'bsc', 'solana'.
    """
    data = await _client.get("/search", params={"q": chain}, use_cache=False)
    pairs = [
        p for p in (data.get("pairs") or [])
        if p.get("chainId", "").lower() == chain.lower()
    ]
    pairs.sort(key=lambda x: x.get("pairCreatedAt", 0) or 0, reverse=True)
    return [_parse_pair(p) for p in pairs[:limit]]


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
