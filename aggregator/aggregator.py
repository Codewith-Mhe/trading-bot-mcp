"""
aggregator/aggregator.py
=========================
Combines all data sources into a single MarketSnapshot in parallel.
This is what the Strategy Agent consumes for full market awareness.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from models.schemas import (
    MarketSnapshot, GlobalMarket,
    TokenData, YieldPool, DexPair, WhaleTransaction,
)
from config.settings import settings

logger = logging.getLogger(__name__)


class DataAggregator:
    def __init__(self) -> None:
        from alerts.alert_engine import AlertEngine
        self._alert_engine = AlertEngine()

    async def get_market_snapshot(
        self,
        chain: str = "ethereum",
        top_n: int = 20,
    ) -> MarketSnapshot:
        """
        Fetch all data sources concurrently and merge into one snapshot.
        Failed sources return empty lists — the snapshot is always returned.
        """
        logger.info("Building snapshot for chain: %s", chain)

        from servers.coingecko_server import get_top_markets, get_global_market
        from servers.defillama_server import get_top_yields
        from servers.dexscreener_server import get_top_gainers
        from servers.whale_tracker_server import get_whale_transactions

        results = await asyncio.gather(
            get_top_markets(limit=top_n),
            get_global_market(),
            get_top_yields(limit=top_n, chain=chain),
            get_top_gainers(chain=chain, limit=10),
            get_whale_transactions(chain=chain, min_usd=settings.whale_threshold_usd, limit=10),
            return_exceptions=True,
        )

        tokens_raw, global_raw, yields_raw, pairs_raw, whales_raw = results

        def safe_list(result, model):
            if isinstance(result, list):
                try:
                    return [model(**item) for item in result]
                except Exception as e:
                    logger.warning("Schema parse error: %s", e)
            return []

        tokens = safe_list(tokens_raw, TokenData)
        yields = safe_list(yields_raw, YieldPool)
        pairs = safe_list(pairs_raw, DexPair)
        whales = safe_list(whales_raw, WhaleTransaction)

        global_market = None
        if isinstance(global_raw, dict):
            try:
                global_market = GlobalMarket(**global_raw)
            except Exception:
                pass

        alerts = await self._alert_engine.evaluate(tokens=tokens, pairs=pairs, whales=whales)

        snapshot = MarketSnapshot(
            global_market=global_market,
            top_tokens=tokens,
            top_yields=yields,
            trending_pairs=pairs,
            recent_whale_moves=whales,
            active_alerts=alerts,
            chain=chain,
        )

        logger.info(
            "Snapshot ready — tokens=%d, yields=%d, pairs=%d, whales=%d, alerts=%d",
            len(tokens), len(yields), len(pairs), len(whales), len(alerts),
        )
        return snapshot

    async def token_deep_dive(self, symbol: str, chain: str = "ethereum") -> dict:
        """Full cross-source data for a single token."""
        from servers.dexscreener_server import search_token_pairs
        from servers.whale_tracker_server import get_smart_money_flow
        from servers.coingecko_server import search_coins, get_coin_details

        # Get CoinGecko ID first
        cg_id = None
        try:
            coins = await search_coins(symbol)
            if coins:
                cg_id = coins[0]["id"]
        except Exception:
            pass

        tasks = [
            search_token_pairs(symbol),
            get_smart_money_flow(symbol, hours=24),
        ]
        if cg_id:
            tasks.append(get_coin_details(cg_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        dex_pairs = results[0] if isinstance(results[0], list) else []
        smart_money = results[1] if isinstance(results[1], dict) else {}
        cg_data = results[2] if len(results) > 2 and isinstance(results[2], dict) else {}

        return {
            "symbol": symbol.upper(),
            "coingecko_data": cg_data,
            "dex_pairs": dex_pairs[:5],
            "smart_money_flow_24h": smart_money,
            "aggregated_at": datetime.utcnow().isoformat(),
        }
