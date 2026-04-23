"""
copy_trade/copy_trade_agent.py
================================
Copy Trade Agent — persistent background process.
Manages multiple WalletWatcher instances (one per watched wallet).
All watchers run in parallel — watching 10 wallets costs the same as watching 1.

Responsibilities:
  - Add / remove wallets to watch
  - Run all watchers concurrently
  - Listen for COPY_TRADE_REQUEST events
  - Gate copy trades through the Safety Scanner
  - Apply user filters (min token age, max trade size, safety score)
  - Re-emit as TRADE_REQUEST so it goes through the full execution pipeline

Also exposes MCP tools so the user (via Telegram) can manage their watchlist.
"""

from __future__ import annotations
import asyncio
import logging
from mcp.server.fastmcp import FastMCP

from copy_trade.wallet_watcher import WalletWatcher, WatchedWallet
from events.event_bus import bus, Event
from safety.scanner import quick_scan
from config.settings import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("copy-trade")

# Pulled from settings (loaded from .env via pydantic-settings)
_ALCHEMY_WS = settings.alchemy_ws_url


class CopyTradeAgent:
    """
    Manages all wallet watchers.
    One asyncio Task per watcher — fully parallel.
    """

    def __init__(self) -> None:
        self._wallets: dict[str, WatchedWallet] = {}    # address → wallet
        self._tasks: dict[str, asyncio.Task] = {}       # address → task
        self._running = False

    # ── Wallet Management ─────────────────────────────────────────────────

    async def add_wallet(self, wallet: WatchedWallet) -> None:
        """Start watching a new wallet address."""
        addr = wallet.address.lower()
        if addr in self._wallets:
            logger.info("Already watching: %s", addr[:10])
            return

        self._wallets[addr] = wallet
        watcher = WalletWatcher(wallet, alchemy_ws_url=_ALCHEMY_WS)

        task = asyncio.create_task(
            watcher.start(),
            name=f"watcher:{addr[:10]}",
        )
        self._tasks[addr] = task
        logger.info(
            "➕ Added wallet watcher: %s (%s) — now watching %d wallet(s)",
            wallet.label or addr[:10], wallet.chain, len(self._wallets)
        )

    async def remove_wallet(self, address: str) -> bool:
        """Stop watching a wallet and clean up."""
        addr = address.lower()
        if addr not in self._wallets:
            return False

        task = self._tasks.pop(addr, None)
        if task:
            task.cancel()

        self._wallets.pop(addr, None)
        logger.info("➖ Removed wallet watcher: %s", addr[:10])
        return True

    def list_wallets(self) -> list[dict]:
        """Return current watchlist."""
        return [
            {
                "address": w.address,
                "label": w.label,
                "chain": w.chain,
                "copy_size_pct": w.copy_size_pct,
                "max_copy_usd": w.max_copy_usd,
                "safety_min_score": w.safety_min_score,
                "notify_only": w.notify_only,
                "trade_count": w.trade_count,
            }
            for w in self._wallets.values()
        ]

    async def start(self) -> None:
        """Register event listeners and keep agent alive."""
        self._running = True
        bus.register(Event.COPY_TRADE_REQUEST, self._handle_copy_trade_request)
        logger.info("🤖 Copy Trade Agent started — watching %d wallet(s)", len(self._wallets))

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(10)

    def stop(self) -> None:
        self._running = False
        for task in self._tasks.values():
            task.cancel()

    # ── Event Handler ─────────────────────────────────────────────────────

    async def _handle_copy_trade_request(self, payload: dict) -> None:
        """
        Received COPY_TRADE_REQUEST from a WalletWatcher.
        Apply safety filters, then re-emit as TRADE_REQUEST.
        """
        ca = payload.get("contract_address", "")
        chain = payload.get("chain", "ethereum")
        copy_usd = payload.get("copy_amount_usd", 0)
        notify_only = payload.get("notify_only", False)
        min_score = payload.get("safety_min_score", 60)
        source_label = payload.get("source_label") or payload.get("source_wallet", "")[:10]

        logger.info(
            "📋 Copy trade request: %s bought %s — running safety check",
            source_label, ca[:10]
        )

        # Run safety check (quick, since we need speed)
        report = await quick_scan(ca, chain)

        # Apply safety gate
        if report.safety_score < min_score:
            logger.warning(
                "Copy trade REJECTED: %s scored %d (min: %d) — %s",
                ca[:10], report.safety_score, min_score, report.recommendation
            )
            # Notify user of the rejection
            await bus.emit(Event.ALPHA_FOUND, {
                "type": "copy_trade_rejected",
                "source_wallet": payload.get("source_wallet"),
                "source_label": source_label,
                "contract_address": ca,
                "chain": chain,
                "safety_score": report.safety_score,
                "reason": f"Safety score {report.safety_score}/100 below minimum {min_score}",
                "warnings": report.warnings,
            })
            return

        if report.is_honeypot:
            logger.warning("Copy trade BLOCKED: %s is a HONEYPOT", ca[:10])
            return

        if notify_only:
            # User wants alerts only, not auto-execution
            await bus.emit(Event.ALPHA_FOUND, {
                "type": "copy_trade_alert",
                "source_wallet": payload.get("source_wallet"),
                "source_label": source_label,
                "contract_address": ca,
                "chain": chain,
                "dex": payload.get("dex"),
                "source_amount_usd": payload.get("source_amount_usd"),
                "safety_score": report.safety_score,
                "safety_summary": report.summary,
                "message": (
                    f"🎯 {source_label} just bought {ca[:10]} on {payload.get('dex', 'DEX')}\n"
                    f"Safety: {report.safety_score}/100 | {report.recommendation}"
                ),
            })
            return

        # All checks passed — re-emit as TRADE_REQUEST into the main pipeline
        logger.info(
            "✅ Copy trade approved: %s | Score: %d/100 | $%.0f",
            ca[:10], report.safety_score, copy_usd
        )
        await bus.emit(Event.TRADE_REQUEST, {
            "contract_address": ca,
            "chain": chain,
            "amount_usd": copy_usd,
            "urgency": "normal",
            "source": "copy_trade",
            "source_wallet": payload.get("source_wallet"),
            "source_label": source_label,
            "dex": payload.get("dex"),
            "safety_score": report.safety_score,
            # Pre-attach safety result so Strategy Agent doesn't need to re-scan
            "safety_result": report.model_dump(),
        })


# ── Module-level agent instance ───────────────────────────────────────────
agent = CopyTradeAgent()


# ── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def watch_wallet(
    wallet_address: str,
    chain: str = "ethereum",
    copy_size_pct: float = 10.0,
    max_copy_usd: float = 500.0,
    safety_min_score: int = 60,
    notify_only: bool = False,
    label: str = "",
) -> dict:
    """
    Start copy trading a wallet address.
    Detects swaps in real-time via WebSocket and optionally replicates them.

    Parameters:
      wallet_address   — the address to watch (EVM)
      chain            — ethereum | base | arbitrum | bsc | polygon
      copy_size_pct    — copy at X% of their trade size (default: 10%)
      max_copy_usd     — never spend more than this per copy trade (default: $500)
      safety_min_score — only copy if safety score >= this (default: 60)
      notify_only      — if True, send alert but don't auto-execute (default: False)
      label            — friendly name for this wallet (optional)

    Example: "Watch 0xabc123 and copy at 10% of their size, max $200"
    """
    wallet = WatchedWallet(
        address=wallet_address,
        label=label or None,
        chain=chain,
        copy_size_pct=copy_size_pct,
        max_copy_usd=max_copy_usd,
        safety_min_score=safety_min_score,
        notify_only=notify_only,
    )
    await agent.add_wallet(wallet)
    return {
        "status": "watching",
        "address": wallet_address,
        "label": label or wallet_address[:10],
        "chain": chain,
        "copy_size_pct": copy_size_pct,
        "max_copy_usd": max_copy_usd,
        "safety_min_score": safety_min_score,
        "notify_only": notify_only,
        "total_watching": len(agent._wallets),
    }


@mcp.tool()
async def unwatch_wallet(wallet_address: str) -> dict:
    """
    Stop copy trading / watching a wallet address.
    Use when you want to stop following a specific wallet.
    """
    removed = await agent.remove_wallet(wallet_address)
    return {
        "status": "removed" if removed else "not_found",
        "address": wallet_address,
        "total_watching": len(agent._wallets),
    }


@mcp.tool()
async def list_watched_wallets() -> list[dict]:
    """
    List all wallets currently being watched for copy trading.
    Returns address, label, chain, copy parameters, and trade count since added.
    """
    return agent.list_wallets()


@mcp.tool()
async def get_wallet_recent_trades(
    wallet_address: str,
    chain: str = "ethereum",
    limit: int = 10,
) -> list[dict]:
    """
    Fetch recent swap transactions for a wallet address using Arkham/DexScreener.
    Use to evaluate whether a wallet is worth copy trading before adding it.
    Returns token, amount, action, and timestamp for each trade.
    """
    # Uses the existing whale tracker tool
    from servers.whale_tracker_server import get_wallet_profile
    profile = await get_wallet_profile(wallet_address, chain)
    return profile.get("top_holdings", [])[:limit]


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
