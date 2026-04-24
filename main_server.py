"""
main_server.py
==============
Unified DeFi MCP Server — single entry point.
Registers all tools from all modules directly onto one FastMCP instance.
This approach works with all versions of the MCP SDK.

Run modes:
  python main_server.py              → stdio (local agent frameworks)
  python main_server.py --http       → HTTP on port 8000
  python main_server.py --sse        → SSE transport (legacy)
  python main_server.py --inspect    → MCP Inspector UI (browser testing)
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from mcp.server.fastmcp import FastMCP

# Force UTF-8 on Windows terminal to avoid encoding errors
import io
utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(utf8_stdout),
        logging.FileHandler("defi_mcp.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Build unified server ──────────────────────────────────────────────────

mcp = FastMCP(
    name="defi-data-mcp",
    instructions=(
        "You are connected to a DeFi intelligence server with real-time market data "
        "and pre-trade safety scanning.\n\n"
        "TOOLS:\n"
        "• DeFiLlama: get_all_protocols, get_protocol_tvl, get_chain_tvl, "
        "get_top_yields, get_stablecoin_overview, get_protocol_fees\n"
        "• DexScreener: search_token_pairs, get_pair_by_address, get_token_all_pairs, "
        "get_top_gainers, get_new_pairs\n"
        "• CoinGecko: get_top_markets, get_coin_details, get_trending_coins, "
        "get_global_market, get_fear_and_greed, get_price_history, search_coins\n"
        "• Whale Tracker: get_whale_transactions, get_wallet_profile, "
        "get_smart_money_flow, lookup_wallet_label, get_exchange_flows\n"
        "• Safety Scanner: check_token_safety_quick, check_token_safety_full, "
        "get_token_safety_cached, batch_safety_scan\n"
        "• Copy Trade: watch_wallet, unwatch_wallet, list_watched_wallets, "
        "get_wallet_recent_trades\n\n"
        "CRITICAL RULE: Always call check_token_safety_quick before any trade. "
        "Never recommend tokens with safety_score < 40 or is_honeypot = true."
    ),
)
app = mcp.get_asgi_app()


# ── Register DeFiLlama tools ──────────────────────────────────────────────

from servers.defillama_server import (
    get_all_protocols,
    get_protocol_tvl,
    get_chain_tvl,
    get_top_yields,
    get_stablecoin_overview,
    get_protocol_fees,
)

mcp.tool()(get_all_protocols)
mcp.tool()(get_protocol_tvl)
mcp.tool()(get_chain_tvl)
mcp.tool()(get_top_yields)
mcp.tool()(get_stablecoin_overview)
mcp.tool()(get_protocol_fees)


# ── Register DexScreener tools ────────────────────────────────────────────

from servers.dexscreener_server import (
    search_token_pairs,
    get_pair_by_address,
    get_token_all_pairs,
    get_top_gainers,
    get_new_pairs,
)

mcp.tool()(search_token_pairs)
mcp.tool()(get_pair_by_address)
mcp.tool()(get_token_all_pairs)
mcp.tool()(get_top_gainers)
mcp.tool()(get_new_pairs)


# ── Register CoinGecko tools ──────────────────────────────────────────────

from servers.coingecko_server import (
    get_top_markets,
    get_coin_details,
    get_trending_coins,
    get_global_market,
    get_fear_and_greed,
    get_price_history,
    search_coins,
)

mcp.tool()(get_top_markets)
mcp.tool()(get_coin_details)
mcp.tool()(get_trending_coins)
mcp.tool()(get_global_market)
mcp.tool()(get_fear_and_greed)
mcp.tool()(get_price_history)
mcp.tool()(search_coins)


# ── Register Whale Tracker tools ──────────────────────────────────────────

from servers.whale_tracker_server import (
    get_whale_transactions,
    get_wallet_profile,
    get_smart_money_flow,
    lookup_wallet_label,
    get_exchange_flows,
)

mcp.tool()(get_whale_transactions)
mcp.tool()(get_wallet_profile)
mcp.tool()(get_smart_money_flow)
mcp.tool()(lookup_wallet_label)
mcp.tool()(get_exchange_flows)


# ── Register Safety Scanner tools ─────────────────────────────────────────

from safety.scanner import (
    check_token_safety_quick,
    check_token_safety_full,
    get_token_safety_cached,
    batch_safety_scan,
    handle_trade_request,
)

mcp.tool()(check_token_safety_quick)
mcp.tool()(check_token_safety_full)
mcp.tool()(get_token_safety_cached)
mcp.tool()(batch_safety_scan)


# ── Register Copy Trade tools ─────────────────────────────────────────────

from copy_trade.copy_trade_agent import (
    watch_wallet,
    unwatch_wallet,
    list_watched_wallets,
    get_wallet_recent_trades,
)

mcp.tool()(watch_wallet)
mcp.tool()(unwatch_wallet)
mcp.tool()(list_watched_wallets)
mcp.tool()(get_wallet_recent_trades)


# ── Register Resources ────────────────────────────────────────────────────

from resources.live_resources import (
    market_snapshot_resource,
    active_alerts_resource,
    fear_greed_resource,
    chain_tvl_resource,
    token_price_resource,
)

mcp.resource("defi://market/snapshot")(market_snapshot_resource)
mcp.resource("defi://market/alerts")(active_alerts_resource)
mcp.resource("defi://market/fear-greed")(fear_greed_resource)
mcp.resource("defi://chain/{chain}/tvl")(chain_tvl_resource)
mcp.resource("defi://token/{symbol}/price")(token_price_resource)


# ── Register Prompts ──────────────────────────────────────────────────────

from prompts.analysis_prompts import (
    market_overview_prompt,
    token_due_diligence_prompt,
    yield_strategy_prompt,
    whale_alert_analysis_prompt,
)

mcp.prompt()(market_overview_prompt)
mcp.prompt()(token_due_diligence_prompt)
mcp.prompt()(yield_strategy_prompt)
mcp.prompt()(whale_alert_analysis_prompt)


# ── Startup checks ────────────────────────────────────────────────────────

async def startup() -> None:
    from utils.ollama_client import OllamaClient
    ok, msg = await OllamaClient().health_check()
    logger.info("[%s] Ollama: %s", "OK" if ok else "WARNING", msg)
    logger.info(
        "✅ DeFi MCP Server ready\n"
        "   Tools: 31 | Resources: 5 | Prompts: 4\n"
        "   Event Bus: active (TRADE_REQUEST -> SAFETY_RESULT | ALPHA_FOUND)"
    )


# ── CLI ───────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeFi MCP Tool Server — Role 3")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--http", action="store_true", help="HTTP transport")
    group.add_argument("--sse", action="store_true", help="SSE transport (legacy)")
    group.add_argument("--inspect", action="store_true", help="MCP Inspector UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(startup())

    if args.inspect:
        # Run with uvicorn directly for HTTP inspection
        import uvicorn
        app = mcp.get_asgi_app()
        logger.info("[INSPECT] HTTP server at http://127.0.0.1:%d", args.port)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.http:
        # Use uvicorn for HTTP transport
        import uvicorn
        app = mcp.get_asgi_app()
        logger.info("[HTTP] on %s:%d", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.sse:
        logger.info("[SSE] stdio transport (sse not supported in this version)")
        mcp.run()
    else:
        logger.info("[READY] stdio transport")
        mcp.run()