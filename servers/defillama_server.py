"""
servers/defillama_server.py
============================
DeFiLlama MCP tools — TVL, protocols, yield pools, stablecoins.
No API key required.
"""

from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from models.schemas import ProtocolTVL, YieldPool
from utils.http_client import AsyncHTTPClient
from config.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("defillama")

_llama = AsyncHTTPClient(base_url=settings.defillama_base_url)
_yields = AsyncHTTPClient(base_url=settings.defillama_yields_url)


# ── Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_all_protocols(limit: int = 50) -> list[dict]:
    """
    List all DeFi protocols tracked by DeFiLlama with current TVL,
    category (DEX, Lending, Yield, Bridge, etc.), supported chains,
    and 24h / 7d TVL change percentages.
    Use for broad protocol discovery or comparing protocol health at scale.
    """
    data = await _llama.get("/protocols")
    return [
        ProtocolTVL(
            protocol=p.get("name", ""),
            tvl_usd=p.get("tvl", 0),
            tvl_by_chain=p.get("chainTvls", {}),
            change_1d_pct=p.get("change_1d"),
            change_7d_pct=p.get("change_7d"),
            category=p.get("category"),
            chains=p.get("chains", []),
        ).model_dump()
        for p in data[:limit]
    ]


@mcp.tool()
async def get_protocol_tvl(protocol_slug: str) -> dict:
    """
    Fetch detailed TVL breakdown for a single DeFi protocol by slug.
    Slug examples: 'uniswap', 'aave', 'compound', 'curve', 'lido', 'makerdao'.
    Returns TVL by chain, 24h and 7d change, category, and supported chains.
    Use before recommending a protocol position to assess liquidity depth and stability.
    """
    data = await _llama.get(f"/protocol/{protocol_slug}")
    tvl_history = data.get("tvl", [])
    current_tvl = tvl_history[-1].get("totalLiquidityUSD", 0) if tvl_history else 0
    return ProtocolTVL(
        protocol=data.get("name", protocol_slug),
        tvl_usd=current_tvl,
        tvl_by_chain=data.get("currentChainTvls", {}),
        change_1d_pct=data.get("change_1d"),
        change_7d_pct=data.get("change_7d"),
        category=data.get("category"),
        chains=data.get("chains", []),
    ).model_dump()


@mcp.tool()
async def get_chain_tvl(chain: str) -> dict:
    """
    Get historical and current TVL for an entire blockchain.
    Chain options: 'Ethereum', 'Base', 'Arbitrum', 'Polygon', 'BSC', 'Optimism', 'Avalanche'.
    Returns current TVL, 24h change %, and total historical data points.
    Use to assess overall chain health and detect capital migration between chains.
    """
    data = await _llama.get(f"/v2/historicalChainTvl/{chain}")
    if isinstance(data, list) and len(data) >= 2:
        latest, prev = data[-1], data[-2]
        change = ((latest["tvl"] - prev["tvl"]) / prev["tvl"] * 100) if prev["tvl"] else 0.0
        return {
            "chain": chain,
            "tvl_usd": latest["tvl"],
            "change_24h_pct": round(change, 2),
            "data_points": len(data),
        }
    return {"chain": chain, "tvl_usd": 0, "error": "insufficient data"}


@mcp.tool()
async def get_top_yields(
    min_tvl_usd: float = 100_000,
    stable_only: bool = False,
    chain: str = "",
    limit: int = 20,
) -> list[dict]:
    """
    Fetch top yield farming and liquidity pool opportunities across all of DeFi.
    Filterable by: minimum TVL (default $100k), stablecoin-only pools, specific chain.
    Returns APY (base + reward), TVL, impermanent loss risk, and 30d outlook prediction.
    Use when the Strategy Agent needs yield-bearing positions to recommend.
    """
    raw = await _yields.get("/pools")
    pools = raw.get("data", [])

    filtered = [
        p for p in pools
        if p.get("tvlUsd", 0) >= min_tvl_usd
        and (not stable_only or p.get("stablecoin", False))
        and (not chain or p.get("chain", "").lower() == chain.lower())
    ]
    filtered.sort(key=lambda x: x.get("apy", 0), reverse=True)

    return [
        YieldPool(
            pool_id=p.get("pool", ""),
            protocol=p.get("project", ""),
            chain=p.get("chain", ""),
            symbol=p.get("symbol", ""),
            apy=round(p.get("apy", 0), 4),
            apy_base=p.get("apyBase"),
            apy_reward=p.get("apyReward"),
            tvl_usd=p.get("tvlUsd"),
            stable_coin=p.get("stablecoin", False),
            il_risk=p.get("ilRisk"),
            outlook=p.get("predictions", {}).get("predictedClass"),
        ).model_dump()
        for p in filtered[:limit]
    ]


@mcp.tool()
async def get_stablecoin_overview() -> list[dict]:
    """
    Get TVL, market cap, and peg health for all major stablecoins.
    Returns price (to detect depeg), circulating supply, and chain distribution.
    Use to monitor stablecoin systemic risk or detect capital rotation signals.
    """
    data = await _llama.get("/stablecoins?includePrices=true")
    return [
        {
            "name": s.get("name"),
            "symbol": s.get("symbol"),
            "price_usd": s.get("price"),
            "circulating_usd": s.get("circulating", {}).get("peggedUSD", 0),
            "chains": list(s.get("chainCirculating", {}).keys()),
            "peg_type": s.get("pegType"),
            "peg_mechanism": s.get("pegMechanism"),
        }
        for s in data.get("peggedAssets", [])[:20]
    ]


@mcp.tool()
async def get_protocol_fees(protocol_slug: str) -> dict:
    """
    Fetch fee and revenue data for a DeFi protocol (where available).
    Returns 24h fees, 7d fees, 30d fees, and annualised revenue.
    Use to assess protocol sustainability and value capture before recommending.
    """
    data = await _llama.get(f"/summary/fees/{protocol_slug}")
    return {
        "protocol": protocol_slug,
        "total_24h_usd": data.get("total24h"),
        "total_7d_usd": data.get("total7d"),
        "total_30d_usd": data.get("total30d"),
        "annual_revenue_usd": data.get("totalAllTime"),
        "source": "defillama",
    }


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
