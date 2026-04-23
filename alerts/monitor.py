"""
alerts/monitor.py
==================
Real-Time Research Agent + Monitor.

Responsibilities:
  - Polls all data sources on a configurable interval (default 60s)
  - Detects market alerts (price spikes, whale moves, DEX anomalies)
  - Detects alpha signals (smart money buys, trending new pairs, convergence)
  - Emits ALPHA_FOUND on the Event Bus → Role 5 Gateway → Telegram/Discord
  - Updates MCP resource cache so agents always have fresh data
  - Dispatches alerts to registered handlers (console, file, Role 4 notifiers)
"""

from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from config.settings import settings
from models.safety_schemas import AlphaSignal
from events.event_bus import bus, Event

logger = logging.getLogger(__name__)

AlertHandler = Callable[[object], Awaitable[None]]


class RealTimeMonitor:
    """
    Research Agent + Monitor in one persistent background process.
    Emits ALPHA_FOUND events when notable market signals are detected.
    """

    def __init__(self) -> None:
        self._alert_handlers: list[AlertHandler] = []
        self._running = False
        self._latest_snapshot = None

    def register_handler(self, handler: AlertHandler) -> None:
        """
        Register an async handler for Alert objects.
        Role 5 registers Telegram/Discord handlers here.
        """
        self._alert_handlers.append(handler)
        logger.info("Alert handler registered: %s", handler.__name__)

    async def start(self, chains: list[str] = ["ethereum", "base", "arbitrum"]) -> None:
        """Start the research + monitoring loop. Runs until stop() is called."""
        from aggregator.aggregator import DataAggregator
        from resources.live_resources import update_snapshot_cache, update_alerts_cache

        aggregator = DataAggregator()
        self._running = True

        logger.info(
            "🟢 Research Agent started — %ds interval | chains: %s",
            settings.poll_interval_seconds,
            ", ".join(chains),
        )

        while self._running:
            for chain in chains:
                try:
                    snapshot = await aggregator.get_market_snapshot(chain=chain)
                    self._latest_snapshot = snapshot

                    # Update MCP resource cache
                    update_snapshot_cache(snapshot.model_dump())
                    update_alerts_cache([a.model_dump() for a in snapshot.active_alerts])

                    # Dispatch alerts to registered handlers
                    for alert in snapshot.active_alerts:
                        await self._dispatch_alert(alert)

                    # Detect alpha and emit ALPHA_FOUND on Event Bus
                    alpha_signals = await self._detect_alpha(snapshot, chain)
                    for signal in alpha_signals:
                        await bus.emit(Event.ALPHA_FOUND, signal.model_dump())
                        logger.info(
                            "💡 ALPHA_FOUND [%s]: %s",
                            signal.confidence.upper(),
                            signal.description[:80],
                        )

                    logger.info(
                        "[%s] tokens=%d | yields=%d | alerts=%d | alpha=%d",
                        chain.upper(),
                        len(snapshot.top_tokens),
                        len(snapshot.top_yields),
                        len(snapshot.active_alerts),
                        len(alpha_signals),
                    )

                except Exception as exc:
                    logger.error("Monitor error on %s: %s", chain, exc, exc_info=True)

            await asyncio.sleep(settings.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
        logger.info("🔴 Research Agent stopped")

    @property
    def latest_snapshot(self):
        return self._latest_snapshot

    # ── Alpha Signal Detection ─────────────────────────────────────────────

    async def _detect_alpha(self, snapshot, chain: str) -> list[AlphaSignal]:
        """
        Scan snapshot for notable alpha signals.
        Emitted as ALPHA_FOUND → Role 5 pushes to user via Telegram/Discord.
        """
        signals: list[AlphaSignal] = []

        # Signal 1: Large labeled whale accumulation
        for whale in snapshot.recent_whale_moves:
            if (
                whale.action == "buy"
                and whale.amount_usd >= settings.whale_threshold_usd * 2
                and whale.wallet_label
            ):
                signals.append(AlphaSignal(
                    signal_type="whale_accumulation",
                    token_symbol=whale.token_symbol,
                    chain=whale.chain,
                    description=(
                        f"🐋 {whale.wallet_label} bought ${whale.amount_usd:,.0f} of "
                        f"{whale.token_symbol} on {whale.chain}. "
                        f"Safety: checking... Want me to ape?"
                    ),
                    amount_usd=whale.amount_usd,
                    source_wallet=whale.wallet_address,
                    source_wallet_label=whale.wallet_label,
                    confidence="high" if whale.amount_usd >= 1_000_000 else "medium",
                    raw_data=whale.model_dump(),
                ))

        # Signal 2: Trending new pair with strong 1h momentum
        for pair in snapshot.trending_pairs:
            vol = pair.volume_24h_usd or 0
            liq = pair.liquidity_usd or 0
            change_1h = pair.price_change_1h_pct or 0

            if vol > 50_000 and liq > 20_000 and change_1h > 20:
                signals.append(AlphaSignal(
                    signal_type="trending_new_pair",
                    token_symbol=pair.base_token_symbol,
                    token_address=pair.pair_address,
                    chain=pair.chain or chain,
                    description=(
                        f"📈 {pair.base_token_symbol} up {change_1h:+.1f}% in 1h on "
                        f"{pair.dex_name} ({pair.chain}). "
                        f"Vol: ${vol:,.0f} | Liq: ${liq:,.0f}. "
                        f"Paste CA to run safety scan."
                    ),
                    amount_usd=vol,
                    confidence="medium",
                    raw_data=pair.model_dump(),
                ))

        # Signal 3: Smart money buy + price trending (high conviction)
        top_gainer_symbols = {
            p.base_token_symbol
            for p in snapshot.trending_pairs
            if (p.price_change_24h_pct or 0) > 15
        }
        for whale in snapshot.recent_whale_moves:
            if (
                whale.token_symbol in top_gainer_symbols
                and whale.action == "buy"
                and whale.amount_usd >= settings.whale_threshold_usd
            ):
                signals.append(AlphaSignal(
                    signal_type="smart_money_buy",
                    token_symbol=whale.token_symbol,
                    chain=whale.chain,
                    description=(
                        f"🔥 HIGH CONVICTION: {whale.token_symbol} is trending +15%+ AND "
                        f"{whale.wallet_label or 'a whale'} just bought "
                        f"${whale.amount_usd:,.0f}. Price + smart money confirmed."
                    ),
                    amount_usd=whale.amount_usd,
                    source_wallet=whale.wallet_address,
                    source_wallet_label=whale.wallet_label,
                    confidence="high",
                    raw_data={"whale": whale.model_dump()},
                ))

        # Signal 4: Top yield opportunity with improving outlook
        for pool in snapshot.top_yields:
            if pool.apy > 50 and pool.outlook == "up" and (pool.tvl_usd or 0) > 500_000:
                signals.append(AlphaSignal(
                    signal_type="yield_opportunity",
                    token_symbol=pool.symbol,
                    chain=pool.chain,
                    description=(
                        f"💰 {pool.symbol} on {pool.protocol} ({pool.chain}) — "
                        f"{pool.apy:.1f}% APY, improving outlook. "
                        f"TVL: ${pool.tvl_usd:,.0f} | IL risk: {pool.il_risk or 'unknown'}."
                    ),
                    amount_usd=pool.tvl_usd,
                    confidence="medium",
                    raw_data=pool.model_dump(),
                ))

        return signals

    async def _dispatch_alert(self, alert) -> None:
        for handler in self._alert_handlers:
            try:
                await handler(alert)
            except Exception as exc:
                logger.error("Alert handler %s failed: %s", handler.__name__, exc)


# ── Built-in Handlers ─────────────────────────────────────────────────────

async def console_handler(alert) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n🚨 [{alert.severity.upper()}] {alert.triggered_at.strftime('%H:%M:%S')}")
    print(f"   {alert.title}\n   {alert.description}\n{bar}")


async def file_handler(alert) -> None:
    with open("alerts.log", "a") as f:
        f.write(json.dumps({
            "id": alert.alert_id,
            "type": alert.alert_type,
            "severity": alert.severity,
            "title": alert.title,
            "timestamp": alert.triggered_at.isoformat(),
            "data": alert.data,
        }) + "\n")


# ── Entry Point ───────────────────────────────────────────────────────────

async def main() -> None:
    monitor = RealTimeMonitor()
    monitor.register_handler(console_handler)
    monitor.register_handler(file_handler)
    # Role 5 adds:  monitor.register_handler(telegram_handler)
    await monitor.start(chains=["ethereum", "base", "arbitrum"])


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
