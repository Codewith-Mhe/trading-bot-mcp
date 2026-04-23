"""
tests/test_servers.py
=====================
Test suite for all MCP tool servers.
Run: pytest tests/ -v

Tests use pytest-asyncio and pytest-httpx to mock HTTP calls
so no real API keys are needed during testing.
"""

import pytest
import json
from unittest.mock import AsyncMock, patch


# ── DeFiLlama Tests ───────────────────────────────────────────────────────

class TestDeFiLlama:

    @pytest.mark.asyncio
    async def test_get_all_protocols_returns_list(self):
        mock_data = [
            {"name": "Uniswap", "tvl": 5_000_000_000, "chainTvls": {"Ethereum": 4e9},
             "change_1d": 1.2, "change_7d": 3.5, "category": "DEX", "chains": ["Ethereum"]},
            {"name": "Aave", "tvl": 8_000_000_000, "chainTvls": {"Ethereum": 7e9},
             "change_1d": -0.5, "change_7d": 2.1, "category": "Lending", "chains": ["Ethereum", "Polygon"]},
        ]
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.defillama_server import get_all_protocols
            result = await get_all_protocols(limit=2)
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["protocol"] == "Uniswap"
            assert result[0]["tvl_usd"] == 5_000_000_000
            assert result[0]["category"] == "DEX"

    @pytest.mark.asyncio
    async def test_get_top_yields_filters_by_min_tvl(self):
        mock_data = {
            "data": [
                {"pool": "pool1", "project": "Curve", "chain": "Ethereum", "symbol": "3CRV",
                 "apy": 12.5, "tvlUsd": 500_000, "stablecoin": True},
                {"pool": "pool2", "project": "Yearn", "chain": "Ethereum", "symbol": "yvUSDC",
                 "apy": 8.2, "tvlUsd": 50_000, "stablecoin": True},  # below threshold
            ]
        }
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.defillama_server import get_top_yields
            result = await get_top_yields(min_tvl_usd=100_000)
            assert len(result) == 1
            assert result[0]["protocol"] == "Curve"

    @pytest.mark.asyncio
    async def test_get_chain_tvl_calculates_change(self):
        mock_data = [
            {"tvl": 100_000_000, "date": 1700000000},
            {"tvl": 110_000_000, "date": 1700086400},
        ]
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.defillama_server import get_chain_tvl
            result = await get_chain_tvl("Ethereum")
            assert result["tvl_usd"] == 110_000_000
            assert result["change_24h_pct"] == pytest.approx(10.0, rel=0.01)


# ── DexScreener Tests ─────────────────────────────────────────────────────

class TestDexScreener:

    @pytest.mark.asyncio
    async def test_search_token_pairs_returns_sorted_by_liquidity(self):
        mock_data = {
            "pairs": [
                {"pairAddress": "0xabc", "baseToken": {"symbol": "LINK"}, "quoteToken": {"symbol": "WETH"},
                 "priceUsd": "7.5", "priceNative": "0.003", "liquidity": {"usd": 5_000_000},
                 "volume": {"h24": 1_000_000}, "priceChange": {"m5": 0.1, "h1": 0.5, "h24": 2.3},
                 "txns": {"h24": {"buys": 200, "sells": 150}}, "dexId": "uniswap", "chainId": "ethereum"},
                {"pairAddress": "0xdef", "baseToken": {"symbol": "LINK"}, "quoteToken": {"symbol": "USDC"},
                 "priceUsd": "7.48", "priceNative": "7.48", "liquidity": {"usd": 1_000_000},
                 "volume": {"h24": 300_000}, "priceChange": {"m5": 0.0, "h1": 0.3, "h24": 2.1},
                 "txns": {"h24": {"buys": 80, "sells": 60}}, "dexId": "sushiswap", "chainId": "ethereum"},
            ]
        }
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.dexscreener_server import search_token_pairs
            result = await search_token_pairs("LINK")
            assert len(result) == 2
            # Should be sorted by liquidity descending
            assert result[0]["liquidity_usd"] >= result[1]["liquidity_usd"]

    @pytest.mark.asyncio
    async def test_get_top_gainers_filters_dust_pairs(self):
        mock_data = {
            "pairs": [
                {"pairAddress": "0x111", "baseToken": {"symbol": "HOT"}, "quoteToken": {"symbol": "ETH"},
                 "priceUsd": "0.01", "priceNative": "0.00001", "liquidity": {"usd": 500},  # dust
                 "volume": {"h24": 1000}, "priceChange": {"h24": 500.0}, "dexId": "uniswap", "chainId": "ethereum"},
                {"pairAddress": "0x222", "baseToken": {"symbol": "ARB"}, "quoteToken": {"symbol": "USDC"},
                 "priceUsd": "1.5", "priceNative": "1.5", "liquidity": {"usd": 50_000},
                 "volume": {"h24": 100_000}, "priceChange": {"h24": 15.0}, "dexId": "uniswap", "chainId": "ethereum"},
            ]
        }
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.dexscreener_server import get_top_gainers
            result = await get_top_gainers(chain="ethereum", min_liquidity=10_000)
            assert len(result) == 1
            assert result[0]["base_token_symbol"] == "ARB"


# ── CoinGecko Tests ───────────────────────────────────────────────────────

class TestCoinGecko:

    @pytest.mark.asyncio
    async def test_get_top_markets_parses_correctly(self):
        mock_data = [
            {"symbol": "btc", "name": "Bitcoin", "current_price": 65000,
             "market_cap": 1_200_000_000_000, "total_volume": 30_000_000_000,
             "price_change_percentage_24h": 2.5, "price_change_percentage_7d_in_currency": 8.1,
             "circulating_supply": 19_500_000},
        ]
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.coingecko_server import get_top_markets
            result = await get_top_markets(limit=1)
            assert result[0]["symbol"] == "BTC"
            assert result[0]["price_usd"] == 65000
            assert result[0]["price_change_24h_pct"] == 2.5
            assert result[0]["source"] == "coingecko"

    @pytest.mark.asyncio
    async def test_get_fear_and_greed_parses_value(self):
        mock_data = {
            "data": [
                {"value": "72", "value_classification": "Greed", "timestamp": "1700000000"},
                {"value": "65", "value_classification": "Greed", "timestamp": "1699913600"},
            ]
        }
        with patch("utils.http_client.AsyncHTTPClient.get", AsyncMock(return_value=mock_data)):
            from servers.coingecko_server import get_fear_and_greed
            result = await get_fear_and_greed(history_days=2)
            assert result["current_value"] == 72
            assert result["current_label"] == "Greed"
            assert len(result["history"]) == 2


# ── Alert Engine Tests ────────────────────────────────────────────────────

class TestAlertEngine:

    @pytest.mark.asyncio
    async def test_price_spike_triggers_above_threshold(self):
        from alerts.alert_engine import AlertEngine
        from models.schemas import TokenData
        engine = AlertEngine()
        tokens = [
            TokenData(symbol="ETH", name="Ethereum", price_usd=3000,
                      price_change_24h_pct=7.5, source="coingecko"),  # above 5% threshold
            TokenData(symbol="BTC", name="Bitcoin", price_usd=65000,
                      price_change_24h_pct=1.2, source="coingecko"),  # below threshold
        ]
        alerts = await engine.evaluate(tokens=tokens)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "price_spike"
        assert "ETH" in alerts[0].title

    @pytest.mark.asyncio
    async def test_whale_move_triggers_above_threshold(self):
        from alerts.alert_engine import AlertEngine
        from models.schemas import WhaleTransaction
        engine = AlertEngine()
        whales = [
            WhaleTransaction(
                wallet_address="0xabc123", token_symbol="ETH",
                amount_usd=500_000, action="sell", chain="ethereum",
                source="arkham",
            )
        ]
        alerts = await engine.evaluate(whales=whales)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "whale_move"

    @pytest.mark.asyncio
    async def test_alert_deduplication(self):
        from alerts.alert_engine import AlertEngine
        from models.schemas import TokenData
        engine = AlertEngine()
        tokens = [
            TokenData(symbol="ETH", name="Ethereum", price_usd=3000,
                      price_change_24h_pct=10.0, source="coingecko"),
        ]
        # First call — should trigger
        alerts1 = await engine.evaluate(tokens=tokens)
        assert len(alerts1) == 1

        # Second call same day — should be deduplicated
        alerts2 = await engine.evaluate(tokens=tokens)
        assert len(alerts2) == 0


# ── Schema Tests ──────────────────────────────────────────────────────────

class TestSchemas:

    def test_token_data_model(self):
        from models.schemas import TokenData
        token = TokenData(symbol="ETH", name="Ethereum", price_usd=3000.0, source="coingecko")
        assert token.symbol == "ETH"
        assert token.price_usd == 3000.0
        d = token.model_dump()
        assert isinstance(d, dict)
        assert "fetched_at" in d

    def test_market_snapshot_defaults_empty(self):
        from models.schemas import MarketSnapshot
        snap = MarketSnapshot()
        assert snap.top_tokens == []
        assert snap.active_alerts == []
        assert snap.chain == "ethereum"

    def test_yield_pool_apy_precision(self):
        from models.schemas import YieldPool
        pool = YieldPool(
            pool_id="test", protocol="Curve", chain="Ethereum",
            symbol="3CRV", apy=12.3456789,
        )
        assert pool.apy == 12.3456789
