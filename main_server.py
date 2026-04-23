"""
main_server.py
==============
Unified DeFi MCP Server — single entry point.
Mounts all tool servers, safety scanner, copy trade agent,
resources, and prompts via FastMCP composition.

Run modes:
  python main_server.py              → stdio (local agent frameworks)
  python main_server.py --http       → streamable-http on port 8000
  python main_server.py --sse        → SSE transport (legacy)
  python main_server.py --inspect    → MCP Inspector UI (browser testing)

Install:
  uv sync                    (recommended)
  pip install -e ".[dev]"    (alternative)
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from mcp.server.fastmcp import FastMCP

# ── Data source servers ───────────────────────────────────────────────────
from servers.defillama_server import mcp as defillama_mcp
from servers.dexscreener_server import mcp as dexscreener_mcp
from servers.coingecko_server import mcp as coingecko_mcp
from servers.whale_tracker_server import mcp as whale_mcp

# ── Safety scanner ────────────────────────────────────────────────────────
from safety.scanner import mcp as safety_mcp

# ── Copy trade agent ──────────────────────────────────────────────────────
from copy_trade.copy_trade_agent import mcp as copy_trade_mcp

# ── Resources + Prompts ───────────────────────────────────────────────────
from resources.live_resources import mcp as resources_mcp
from prompts.analysis_prompts import mcp as prompts_mcp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("defi_mcp.log"),
    ],
)
logger = logging.getLogger(__name__)


# ── Build unified server via FastMCP composition ──────────────────────────

mcp = FastMCP(
    name="defi-data-mcp",
    instructions=(
        "You are connected to a DeFi intelligence server with real-time market data "
        "and pre-trade safety scanning.\n\n"
        "TOOLS (26 total):\n"
        "• DeFiLlama: TVL, yields, protocol fees, stablecoins\n"
        "• DexScreener: DEX prices, liquidity, new pairs, top gainers\n"
        "• CoinGecko: market cap, sentiment, fear/greed, price history\n"
        "• Whale Tracker (Arkham/Nansen): whale txns, smart money flows, exchange flows\n"
        "• Safety Scanner: check_token_safety_quick (3s), check_token_safety_full (10s), "
        "batch_safety_scan — ALWAYS run before executing any trade\n"
        "• Copy Trade: watch_wallet, unwatch_wallet, list_watched_wallets\n\n"
        "RESOURCES:\n"
        "• defi://market/snapshot — live market snapshot\n"
        "• defi://market/alerts — active alerts\n"
        "• defi://market/fear-greed — current sentiment\n"
        "• defi://chain/{chain}/tvl — chain TVL\n"
        "• defi://token/{symbol}/price — token price\n\n"
        "PROMPTS: market_overview_prompt, token_due_diligence_prompt, "
        "yield_strategy_prompt, whale_alert_analysis_prompt\n\n"
        "CRITICAL RULE: Always call check_token_safety_quick before any trade recommendation. "
        "Never recommend buying a token with safety_score < 40 or is_honeypot = true."
    ),
)

# Mount all sub-servers
mcp.mount("defillama", defillama_mcp)
mcp.mount("dexscreener", dexscreener_mcp)
mcp.mount("coingecko", coingecko_mcp)
mcp.mount("whales", whale_mcp)
mcp.mount("safety", safety_mcp)
mcp.mount("copytrade", copy_trade_mcp)
mcp.mount("resources", resources_mcp)
mcp.mount("prompts", prompts_mcp)


# ── Startup checks ────────────────────────────────────────────────────────

async def startup() -> None:
    from utils.ollama_client import OllamaClient
    ok, msg = await OllamaClient().health_check()
    logger.info("%s Ollama: %s", "✅" if ok else "⚠️ ", msg)
    logger.info(
        "✅ DeFi MCP Server ready\n"
        "   Tools: 26 (data: 22 | safety: 4 | copy trade: 3)\n"
        "   Resources: 5\n"
        "   Prompts: 4\n"
        "   Event Bus: active (TRADE_REQUEST → SAFETY_RESULT | ALPHA_FOUND)"
    )


# ── CLI ───────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeFi MCP Tool Server — Role 3")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--http", action="store_true", help="Streamable-HTTP transport")
    group.add_argument("--sse", action="store_true", help="SSE transport (legacy)")
    group.add_argument("--inspect", action="store_true", help="Launch MCP Inspector UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(startup())

    if args.inspect:
        import subprocess
        subprocess.run(["mcp", "dev", __file__])
    elif args.http:
        logger.info("🌐 HTTP on %s:%d", args.host, args.port)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.sse:
        logger.info("📡 SSE on %s:%d", args.host, args.port)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        logger.info("🔌 stdio transport")
        mcp.run()
