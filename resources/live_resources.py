"""
resources/live_resources.py
============================
MCP Resources — live data feeds agents can subscribe to and read.
Resources are like GET endpoints: they expose data the LLM can load
into context without explicitly calling a tool each time.

Think of these as a live "data feed" the agent can read at any point.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("defi-resources")

# Shared state updated by the monitor loop
_snapshot_cache: dict = {}
_alerts_cache: list = []


# ── Market Snapshot Resource ──────────────────────────────────────────────

@mcp.resource("defi://market/snapshot")
async def market_snapshot_resource() -> str:
    """
    Live market snapshot — top tokens, yields, trending pairs, and active alerts.
    Updated every 60 seconds by the monitor loop.
    Agents can read this to get a full market overview without calling individual tools.
    """
    if not _snapshot_cache:
        return json.dumps({"status": "warming_up", "message": "Snapshot not yet available. Call get_top_markets first."})
    return json.dumps(_snapshot_cache, default=str)


@mcp.resource("defi://market/alerts")
async def active_alerts_resource() -> str:
    """
    Currently active market alerts — price spikes, whale moves, DEX anomalies.
    Updated in real-time as alerts are triggered.
    Agents should poll this resource to stay aware of urgent market events.
    """
    return json.dumps(_alerts_cache, default=str)


@mcp.resource("defi://market/fear-greed")
async def fear_greed_resource() -> str:
    """
    Current Crypto Fear & Greed Index value and classification.
    Cached and refreshed every 30 minutes.
    Use as a quick sentiment check before any strategy decision.
    """
    from utils.http_client import AsyncHTTPClient
    client = AsyncHTTPClient(base_url="https://api.alternative.me")
    try:
        data = await client.get("/fng/?limit=1")
        entry = data.get("data", [{}])[0]
        return json.dumps({
            "value": int(entry.get("value", 0)),
            "label": entry.get("value_classification"),
            "updated_at": datetime.utcnow().isoformat(),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.resource("defi://chain/{chain}/tvl")
async def chain_tvl_resource(chain: str) -> str:
    """
    Live TVL for a specific chain (e.g. Ethereum, Base, Arbitrum).
    Refreshed every minute. Use to monitor capital flows between chains.
    """
    from utils.http_client import AsyncHTTPClient
    from config.settings import settings
    client = AsyncHTTPClient(base_url=settings.defillama_base_url)
    try:
        data = await client.get(f"/v2/historicalChainTvl/{chain}")
        if isinstance(data, list) and data:
            latest = data[-1]
            return json.dumps({
                "chain": chain,
                "tvl_usd": latest.get("tvl"),
                "date": latest.get("date"),
                "fetched_at": datetime.utcnow().isoformat(),
            })
    except Exception as exc:
        return json.dumps({"chain": chain, "error": str(exc)})
    return json.dumps({"chain": chain, "error": "no data"})


@mcp.resource("defi://token/{symbol}/price")
async def token_price_resource(symbol: str) -> str:
    """
    Live price for a token by symbol (e.g. ETH, BTC, LINK, ARB).
    Pulled from DexScreener. Use as a quick price lookup without calling a full tool.
    """
    from utils.http_client import AsyncHTTPClient
    from config.settings import settings
    client = AsyncHTTPClient(base_url=settings.dexscreener_base_url)
    try:
        data = await client.get("/search", params={"q": symbol}, use_cache=False)
        pairs = sorted(
            data.get("pairs") or [],
            key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0,
            reverse=True,
        )
        if pairs:
            top = pairs[0]
            return json.dumps({
                "symbol": symbol.upper(),
                "price_usd": top.get("priceUsd"),
                "chain": top.get("chainId"),
                "dex": top.get("dexId"),
                "liquidity_usd": top.get("liquidity", {}).get("usd"),
                "fetched_at": datetime.utcnow().isoformat(),
            })
    except Exception as exc:
        return json.dumps({"symbol": symbol, "error": str(exc)})
    return json.dumps({"symbol": symbol, "error": "no pairs found"})


# ── Cache updaters (called by monitor loop) ───────────────────────────────

def update_snapshot_cache(snapshot_dict: dict) -> None:
    global _snapshot_cache
    _snapshot_cache = snapshot_dict


def update_alerts_cache(alerts: list) -> None:
    global _alerts_cache
    _alerts_cache = alerts
