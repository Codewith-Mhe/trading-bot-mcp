"""
servers/coingecko_server.py
============================
CoinGecko MCP tools — market data, sentiment, fear/greed, price history.
Requires: Free API key from https://www.coingecko.com/en/api
"""

from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from models.schemas import TokenData, GlobalMarket
from utils.http_client import AsyncHTTPClient
from config.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("coingecko")

_cg = AsyncHTTPClient(
    base_url=settings.coingecko_base_url,
    headers={"x-cg-demo-api-key": settings.coingecko_api_key},
)

# Fear & Greed uses a separate free service
_altme = AsyncHTTPClient(base_url="https://api.alternative.me")


# ── Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_top_markets(
    limit: int = 50,
    order: str = "market_cap_desc",
    vs_currency: str = "usd",
) -> list[dict]:
    """
    Fetch top cryptocurrencies with full price, volume, and market data.
    Returns 24h and 7d price change %, circulating supply, and market cap.
    Order options: 'market_cap_desc', 'volume_desc', 'gecko_desc'.
    Use to get a full market overview or identify top-cap opportunities.
    """
    data = await _cg.get("/coins/markets", params={
        "vs_currency": vs_currency,
        "order": order,
        "per_page": limit,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h,7d",
    })
    return [
        TokenData(
            symbol=c.get("symbol", "").upper(),
            name=c.get("name", ""),
            price_usd=c.get("current_price", 0),
            market_cap=c.get("market_cap"),
            volume_24h=c.get("total_volume"),
            price_change_24h_pct=c.get("price_change_percentage_24h"),
            price_change_7d_pct=c.get("price_change_percentage_7d_in_currency"),
            circulating_supply=c.get("circulating_supply"),
            source="coingecko",
        ).model_dump()
        for c in data
    ]


@mcp.tool()
async def get_coin_details(coin_id: str) -> dict:
    """
    Deep-dive data for a specific coin by its CoinGecko ID.
    ID examples: 'bitcoin', 'ethereum', 'uniswap', 'aave', 'chainlink', 'arbitrum'.
    Returns sentiment votes, ATH/ATL, developer activity, community stats,
    and contract addresses across all supported chains.
    Use for full due diligence before recommending a position.
    """
    data = await _cg.get(f"/coins/{coin_id}", params={
        "localization": False,
        "tickers": False,
        "market_data": True,
        "community_data": True,
        "developer_data": False,
    })
    md = data.get("market_data", {})
    return {
        "id": coin_id,
        "name": data.get("name"),
        "symbol": data.get("symbol", "").upper(),
        "price_usd": md.get("current_price", {}).get("usd"),
        "market_cap_usd": md.get("market_cap", {}).get("usd"),
        "volume_24h_usd": md.get("total_volume", {}).get("usd"),
        "price_change_24h_pct": md.get("price_change_percentage_24h"),
        "price_change_7d_pct": md.get("price_change_percentage_7d"),
        "price_change_30d_pct": md.get("price_change_percentage_30d"),
        "ath_usd": md.get("ath", {}).get("usd"),
        "ath_change_pct": md.get("ath_change_percentage", {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
        "sentiment_up_pct": data.get("sentiment_votes_up_percentage"),
        "community_score": data.get("community_score"),
        "contract_addresses": data.get("platforms", {}),
        "categories": data.get("categories", []),
        "source": "coingecko",
    }


@mcp.tool()
async def get_trending_coins() -> list[dict]:
    """
    Get the top trending cryptocurrencies on CoinGecko in the last 24 hours,
    ranked by search volume and community interest (up to 7 results).
    Returns rank, symbol, market cap rank, and current price in BTC.
    Use to spot narrative momentum or identify early market movers.
    """
    data = await _cg.get("/search/trending")
    return [
        {
            "rank": item["item"].get("score", i) + 1,
            "name": item["item"].get("name"),
            "symbol": item["item"].get("symbol"),
            "market_cap_rank": item["item"].get("market_cap_rank"),
            "price_btc": item["item"].get("price_btc"),
            "coin_id": item["item"].get("id"),
            "source": "coingecko",
        }
        for i, item in enumerate(data.get("coins", []))
    ]


@mcp.tool()
async def get_global_market() -> dict:
    """
    Fetch the global crypto market overview: total market cap, 24h volume,
    Bitcoin dominance, Ethereum dominance, number of active cryptocurrencies.
    Use to gauge overall market health before making any allocation decisions.
    """
    data = await _cg.get("/global")
    d = data.get("data", {})
    return GlobalMarket(
        total_market_cap_usd=d.get("total_market_cap", {}).get("usd"),
        total_volume_24h_usd=d.get("total_volume", {}).get("usd"),
        market_cap_change_24h_pct=d.get("market_cap_change_percentage_24h_usd"),
        btc_dominance_pct=d.get("market_cap_percentage", {}).get("btc"),
        eth_dominance_pct=d.get("market_cap_percentage", {}).get("eth"),
        active_cryptocurrencies=d.get("active_cryptocurrencies"),
    ).model_dump()


@mcp.tool()
async def get_fear_and_greed(history_days: int = 7) -> dict:
    """
    Fetch the Crypto Fear & Greed Index — a sentiment indicator from 0 (Extreme Fear)
    to 100 (Extreme Greed) — plus historical values for the last N days.
    Use to calibrate risk tolerance: buy zones near 'Fear', caution near 'Greed'.
    Data from alternative.me (free, no key required).
    """
    data = await _altme.get(f"/fng/?limit={history_days}")
    entries = data.get("data", [])
    latest = entries[0] if entries else {}
    return {
        "current_value": int(latest.get("value", 0)),
        "current_label": latest.get("value_classification"),
        "history": [
            {"value": int(e["value"]), "label": e["value_classification"]}
            for e in entries
        ],
        "source": "alternative.me",
    }


@mcp.tool()
async def get_price_history(
    coin_id: str,
    days: int = 7,
    vs_currency: str = "usd",
) -> dict:
    """
    Historical price data for a coin over N days (1, 7, 14, 30, 90, 180, 365).
    Returns timestamped price points suitable for trend analysis.
    Use to evaluate price trajectories before making trade recommendations.
    Coin ID examples: 'bitcoin', 'ethereum', 'uniswap', 'aave'.
    """
    data = await _cg.get(f"/coins/{coin_id}/market_chart", params={
        "vs_currency": vs_currency,
        "days": days,
    })
    prices = data.get("prices", [])
    return {
        "coin_id": coin_id,
        "currency": vs_currency,
        "days": days,
        "data_points": len(prices),
        "prices": [{"timestamp_ms": p[0], "price_usd": p[1]} for p in prices],
        "source": "coingecko",
    }


@mcp.tool()
async def search_coins(query: str) -> list[dict]:
    """
    Search for coins, tokens, and exchanges by name or symbol.
    Returns matching coins with their CoinGecko ID (needed for other tools),
    market cap rank, and token type.
    Use when you have a token name but need its CoinGecko ID to call other tools.
    """
    data = await _cg.get("/search", params={"query": query})
    return [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "symbol": c.get("symbol"),
            "market_cap_rank": c.get("market_cap_rank"),
            "thumb": c.get("thumb"),
        }
        for c in data.get("coins", [])[:10]
    ]


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
