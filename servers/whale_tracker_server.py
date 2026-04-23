"""
servers/whale_tracker_server.py
================================
Whale tracking MCP tools — large wallet transactions, smart money flows.
Primary: Arkham Intelligence API
Fallback: Nansen API
Requires: ARKHAM_API_KEY (and optionally NANSEN_API_KEY) in .env
"""

from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from models.schemas import WhaleTransaction
from utils.http_client import AsyncHTTPClient
from config.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("whale-tracker")

_arkham = AsyncHTTPClient(
    base_url=settings.arkham_base_url,
    headers={"API-Key": settings.arkham_api_key},
)
_nansen = AsyncHTTPClient(
    base_url=settings.nansen_base_url,
    headers={"apiKey": settings.nansen_api_key},
)


# ── Helper ────────────────────────────────────────────────────────────────

def _infer_action(from_entity: dict, to_entity: dict) -> str:
    from_type = from_entity.get("arkhamEntity", {}).get("type", "")
    to_type = to_entity.get("arkhamEntity", {}).get("type", "")
    if to_type == "exchange":
        return "sell"
    if from_type == "exchange":
        return "buy"
    if "bridge" in (from_type + to_type).lower():
        return "bridge"
    return "transfer"


# ── Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_whale_transactions(
    chain: str = "ethereum",
    min_usd: float = 100_000,
    limit: int = 20,
) -> list[dict]:
    """
    Fetch recent large on-chain transactions above a USD threshold.
    Returns wallet address, wallet label (e.g. 'Binance Hot Wallet'), token,
    USD amount, and action type (buy/sell/transfer/bridge).
    Default minimum: $100,000. Chains: ethereum, base, arbitrum, bsc, polygon.
    Use to detect institutional or smart money activity before it hits the news.
    Falls back to Nansen if Arkham is unavailable.
    """
    try:
        data = await _arkham.get("/transfers", params={
            "usdGte": min_usd,
            "chain": chain,
            "limit": limit,
            "sortKey": "blockTimestamp",
            "sortDir": "desc",
        }, use_cache=False)

        results = []
        for t in data.get("transfers", []):
            from_e = t.get("fromAddress", {})
            to_e = t.get("toAddress", {})
            token = (t.get("tokenTransfers") or [{}])[0]
            results.append(WhaleTransaction(
                tx_hash=t.get("transactionHash"),
                wallet_address=from_e.get("address", ""),
                wallet_label=from_e.get("arkhamEntity", {}).get("name"),
                token_symbol=token.get("tokenSymbol", "UNKNOWN"),
                amount_usd=t.get("unitValue", 0),
                amount_tokens=token.get("tokenAmount"),
                action=_infer_action(from_e, to_e),
                chain=chain,
                protocol=to_e.get("arkhamEntity", {}).get("name"),
                source="arkham",
            ).model_dump())
        return results

    except Exception as exc:
        logger.warning("Arkham failed (%s), falling back to Nansen", exc)
        return await _get_whale_txns_nansen(chain, min_usd, limit)


@mcp.tool()
async def get_wallet_profile(wallet_address: str, chain: str = "ethereum") -> dict:
    """
    Full token portfolio and entity profile for a wallet address.
    Returns label (exchange, fund, protocol, or unlabeled), total USD value,
    and top token holdings.
    Use after identifying a whale address to understand who they are and
    what assets they hold.
    """
    try:
        data = await _arkham.get(f"/address/{wallet_address}", params={"chain": chain})
        entity = data.get("arkhamEntity", {})
        return {
            "address": wallet_address,
            "label": entity.get("name", "Unlabeled"),
            "entity_type": entity.get("type", "unknown"),
            "total_usd_value": data.get("totalUSDValue"),
            "top_holdings": [
                {
                    "token": h.get("tokenName"),
                    "symbol": h.get("tokenSymbol"),
                    "balance": h.get("amount"),
                    "usd_value": h.get("usdValue"),
                }
                for h in data.get("tokenBalances", [])[:20]
            ],
            "chain": chain,
            "source": "arkham",
        }
    except Exception as exc:
        logger.error("Wallet profile failed for %s: %s", wallet_address, exc)
        return {"address": wallet_address, "error": str(exc), "source": "arkham"}


@mcp.tool()
async def get_smart_money_flow(token_symbol: str, hours: int = 24) -> dict:
    """
    Net buy/sell flow from labeled smart money wallets for a specific token.
    Smart money includes known hedge funds, on-chain profitable traders, and DeFi whales.
    Returns net flow direction (accumulation vs distribution), total inflow/outflow,
    and top buyer/seller wallets over the last N hours.
    Use to detect institutional conviction before making a trade recommendation.
    """
    try:
        data = await _arkham.get("/token/flows", params={
            "tokenSymbol": token_symbol,
            "hours": hours,
        }, use_cache=False)
        net = data.get("netFlowUSD", 0) or 0
        return {
            "token": token_symbol,
            "period_hours": hours,
            "direction": "accumulation" if net > 0 else "distribution",
            "net_flow_usd": net,
            "total_inflow_usd": data.get("inflowUSD"),
            "total_outflow_usd": data.get("outflowUSD"),
            "top_buyers": data.get("topBuyers", [])[:5],
            "top_sellers": data.get("topSellers", [])[:5],
            "source": "arkham",
        }
    except Exception as exc:
        logger.error("Smart money flow failed for %s: %s", token_symbol, exc)
        return {"token": token_symbol, "error": str(exc), "source": "arkham"}


@mcp.tool()
async def lookup_wallet_label(wallet_address: str) -> dict:
    """
    Identify the entity behind a wallet address.
    Returns label (e.g. 'Coinbase', 'a16z', 'Vitalik Buterin'), entity type,
    associated tags, and social links if available.
    Use to quickly identify if an unknown address belongs to a notable entity.
    """
    try:
        data = await _arkham.get(f"/address/{wallet_address}")
        entity = data.get("arkhamEntity", {})
        return {
            "address": wallet_address,
            "label": entity.get("name", "Unlabeled"),
            "type": entity.get("type", "unknown"),
            "tags": entity.get("tags", []),
            "website": entity.get("website"),
            "twitter": entity.get("twitter"),
            "source": "arkham",
        }
    except Exception as exc:
        return {"address": wallet_address, "label": "Unlabeled", "error": str(exc)}


@mcp.tool()
async def get_exchange_flows(exchange: str = "binance", hours: int = 24) -> dict:
    """
    Track net token flows into and out of a centralized exchange.
    Inflows generally signal intent to sell; outflows signal accumulation.
    Exchange options: 'binance', 'coinbase', 'kraken', 'okx', 'bybit'.
    Returns net flow, top tokens flowing in/out, and total transaction count.
    Use to gauge market sentiment and predict near-term selling pressure.
    """
    try:
        data = await _arkham.get("/exchange/flows", params={
            "exchange": exchange,
            "hours": hours,
        }, use_cache=False)
        return {
            "exchange": exchange,
            "period_hours": hours,
            "net_flow_usd": data.get("netFlowUSD"),
            "inflow_usd": data.get("inflowUSD"),
            "outflow_usd": data.get("outflowUSD"),
            "top_inflow_tokens": data.get("topInflowTokens", [])[:5],
            "top_outflow_tokens": data.get("topOutflowTokens", [])[:5],
            "tx_count": data.get("transactionCount"),
            "source": "arkham",
        }
    except Exception as exc:
        logger.error("Exchange flow lookup failed: %s", exc)
        return {"exchange": exchange, "error": str(exc), "source": "arkham"}


# ── Nansen Fallback ───────────────────────────────────────────────────────

async def _get_whale_txns_nansen(chain: str, min_usd: float, limit: int) -> list[dict]:
    try:
        data = await _nansen.get("/api/smartmoney/transactions", params={
            "chain": chain, "minValue": min_usd, "limit": limit,
        }, use_cache=False)
        return [
            WhaleTransaction(
                tx_hash=t.get("hash"),
                wallet_address=t.get("from", ""),
                wallet_label=t.get("fromLabel"),
                token_symbol=t.get("token", "UNKNOWN"),
                amount_usd=t.get("value", 0),
                action=t.get("type", "transfer"),
                chain=chain,
                source="nansen",
            ).model_dump()
            for t in data.get("data", [])
        ]
    except Exception as exc:
        logger.error("Nansen fallback also failed: %s", exc)
        return []


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
