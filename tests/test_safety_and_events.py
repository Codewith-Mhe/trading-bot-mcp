import asyncio
import sys
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTokenCache:

    def test_cache_miss_on_empty(self):
        from utils.token_cache import TokenCache
        cache = TokenCache()
        assert cache.get("ethereum", "0xabc123") is None

    def test_cache_hit_after_set(self):
        from utils.token_cache import TokenCache, CachedTokenScan
        cache = TokenCache()
        scan = CachedTokenScan(contract_address="0xabc123", chain="ethereum", safety_score=75,
            is_honeypot=False, warnings=[], raw_goplus={}, raw_tokensniffer={}, raw_honeypot={})
        cache.set(scan)
        result = cache.get("ethereum", "0xabc123")
        assert result is not None
        assert result.safety_score == 75

    def test_cache_is_case_insensitive(self):
        from utils.token_cache import TokenCache, CachedTokenScan
        cache = TokenCache()
        scan = CachedTokenScan(contract_address="0xABC123", chain="Ethereum", safety_score=80,
            is_honeypot=False, warnings=[], raw_goplus={}, raw_tokensniffer={}, raw_honeypot={})
        cache.set(scan)
        assert cache.get("ethereum", "0xabc123") is not None

    def test_stale_cache_returns_none(self):
        from utils.token_cache import TokenCache, CachedTokenScan
        cache = TokenCache()
        scan = CachedTokenScan(contract_address="0xold", chain="ethereum", safety_score=50,
            is_honeypot=False, warnings=[], raw_goplus={}, raw_tokensniffer={}, raw_honeypot={},
            scanned_at=datetime.utcnow() - timedelta(minutes=10))
        cache._store["ethereum:0xold"] = scan
        assert cache.get("ethereum", "0xold") is None

    def test_clear_stale_removes_expired(self):
        from utils.token_cache import TokenCache, CachedTokenScan
        cache = TokenCache()
        old = CachedTokenScan(contract_address="0xold", chain="ethereum", safety_score=50,
            is_honeypot=False, warnings=[], raw_goplus={}, raw_tokensniffer={}, raw_honeypot={},
            scanned_at=datetime.utcnow() - timedelta(minutes=10))
        fresh = CachedTokenScan(contract_address="0xfresh", chain="ethereum", safety_score=80,
            is_honeypot=False, warnings=[], raw_goplus={}, raw_tokensniffer={}, raw_honeypot={})
        cache._store["ethereum:0xold"] = old
        cache.set(fresh)
        assert cache.clear_stale() == 1
        assert cache.size() == 1


class TestSafetyScoring:

    def _make_goplus(self, **kwargs):
        from models.safety_schemas import GoPlusResult
        return GoPlusResult(**kwargs)

    def _make_honeypot(self, **kwargs):
        from models.safety_schemas import HoneypotResult
        return HoneypotResult(**kwargs)

    def _make_ts(self, **kwargs):
        from models.safety_schemas import TokenSnifferResult
        if "score" not in kwargs:
            kwargs["score"] = 50
        return TokenSnifferResult(**kwargs)

    def test_honeypot_returns_zero(self):
        from safety.scanner import _calculate_score
        score, warnings = _calculate_score(self._make_goplus(is_honeypot=True), self._make_honeypot(), self._make_ts())
        assert score == 0
        assert any("HONEYPOT" in w for w in warnings)

    def test_honeypot_from_honeypot_api(self):
        from safety.scanner import _calculate_score
        score, _ = _calculate_score(self._make_goplus(), self._make_honeypot(is_honeypot=True, reason="Cannot sell"), self._make_ts())
        assert score == 0

    def test_clean_token_scores_high(self):
        from safety.scanner import _calculate_score
        score, warnings = _calculate_score(
            self._make_goplus(lp_locked_pct=95, top_10_holder_pct=20),
            self._make_honeypot(simulation_success=True),
            self._make_ts(score=85)
        )
        assert score >= 75
        assert len(warnings) == 0

    def test_blacklist_deducts_points(self):
        from safety.scanner import _calculate_score
        score, warnings = _calculate_score(self._make_goplus(has_blacklist=True), self._make_honeypot(), self._make_ts())
        assert score <= 70
        assert any("blacklist" in w.lower() for w in warnings)

    def test_high_sell_tax_deducts_points(self):
        from safety.scanner import _calculate_score
        score, warnings = _calculate_score(self._make_goplus(sell_tax_pct=25.0), self._make_honeypot(), self._make_ts())
        assert score <= 75
        assert any("sell tax" in w.lower() for w in warnings)

    def test_unlocked_lp_deducts_points(self):
        from safety.scanner import _calculate_score
        _, warnings = _calculate_score(self._make_goplus(lp_locked_pct=10.0), self._make_honeypot(), self._make_ts())
        assert any("LP" in w for w in warnings)

    def test_risk_level_from_score(self):
        from safety.scanner import _risk_level
        from models.safety_schemas import RiskLevel
        assert _risk_level(90, False) == RiskLevel.SAFE
        assert _risk_level(65, False) == RiskLevel.LOW
        assert _risk_level(45, False) == RiskLevel.MEDIUM
        assert _risk_level(25, False) == RiskLevel.HIGH
        assert _risk_level(10, False) == RiskLevel.CRITICAL
        assert _risk_level(80, True) == RiskLevel.CRITICAL


class TestEventBus:

    @pytest.mark.asyncio
    async def test_handler_receives_payload(self):
        from events.event_bus import EventBus, Event
        bus = EventBus()
        received = []
        @bus.on(Event.SAFETY_RESULT)
        async def handler(payload: dict):
            received.append(payload)
        await bus.emit(Event.SAFETY_RESULT, {"safety_score": 80, "chain": "ethereum"})
        assert len(received) == 1
        assert received[0]["safety_score"] == 80

    @pytest.mark.asyncio
    async def test_multiple_handlers_run_concurrently(self):
        from events.event_bus import EventBus, Event
        bus = EventBus()
        order = []
        @bus.on(Event.TRADE_REQUEST)
        async def handler_a(payload: dict):
            await asyncio.sleep(0.05)
            order.append("A")
        @bus.on(Event.TRADE_REQUEST)
        async def handler_b(payload: dict):
            order.append("B")
        await bus.emit(Event.TRADE_REQUEST, {"contract_address": "0xabc"})
        assert "A" in order
        assert "B" in order

    @pytest.mark.asyncio
    async def test_failed_handler_does_not_block_others(self):
        from events.event_bus import EventBus, Event
        bus = EventBus()
        success_ran = []
        @bus.on(Event.ALPHA_FOUND)
        async def failing_handler(payload: dict):
            raise ValueError("intentional")
        @bus.on(Event.ALPHA_FOUND)
        async def success_handler(payload: dict):
            success_ran.append(True)
        await bus.emit(Event.ALPHA_FOUND, {"signal_type": "test"})
        assert len(success_ran) == 1

    @pytest.mark.asyncio
    async def test_no_listeners_does_not_raise(self):
        from events.event_bus import EventBus, Event
        bus = EventBus()
        await bus.emit(Event.EXECUTE_SELL, {"position_id": "123"})

    @pytest.mark.asyncio
    async def test_recent_events_log(self):
        from events.event_bus import EventBus, Event
        bus = EventBus()
        await bus.emit(Event.SAFETY_RESULT, {"safety_score": 70})
        log = bus.recent_events(5)
        assert len(log) >= 1
        assert log[-1]["event"] == "SAFETY_RESULT"


class TestSafetyMCPTools:

    @pytest.mark.asyncio
    async def test_quick_scan_returns_report(self):
        from models.safety_schemas import GoPlusResult, HoneypotResult
        real_goplus = GoPlusResult(is_honeypot=False, has_mint_function=False, has_blacklist=False,
            has_pause_function=False, is_proxy=False, has_hidden_owner=False,
            buy_tax_pct=0.0, sell_tax_pct=3.0, lp_locked_pct=95.0, top_10_holder_pct=25.0, raw={})
        real_honeypot = HoneypotResult(is_honeypot=False, simulation_success=True,
            buy_tax_pct=0.0, sell_tax_pct=3.0, raw={})
        with patch("safety.scanner.scan_goplus", AsyncMock(return_value=real_goplus)), \
             patch("safety.scanner.scan_honeypot", AsyncMock(return_value=real_honeypot)):
            from safety.scanner import quick_scan
            report = await quick_scan("0xtest123", "ethereum")
            assert report.contract_address == "0xtest123"
            assert report.chain == "ethereum"
            assert isinstance(report.safety_score, int)
            assert 0 <= report.safety_score <= 100
            assert report.is_honeypot is False
            assert report.recommendation != ""

    @pytest.mark.asyncio
    async def test_batch_scan_handles_failures(self):
        async def mock_quick_scan(ca, chain):
            if ca == "0xbad":
                raise ValueError("API error")
            from models.safety_schemas import SafetyReport, RiskLevel
            return SafetyReport(contract_address=ca, chain=chain, safety_score=70,
                risk_level=RiskLevel.LOW, summary="ok", recommendation="SAFE TO BUY")
        with patch("safety.scanner.quick_scan", side_effect=mock_quick_scan):
            from safety.scanner import batch_safety_scan
            results = await batch_safety_scan(["0xgood1", "0xbad", "0xgood2"], "ethereum")
            assert len(results) == 3
            assert "error" in results[1]
            assert results[0].get("safety_score") == 70


class TestCopyTradeAgent:

    @pytest.mark.asyncio
    async def test_add_and_list_wallet(self):
        from copy_trade.copy_trade_agent import CopyTradeAgent
        from copy_trade.wallet_watcher import WatchedWallet
        agent = CopyTradeAgent()
        wallet = WatchedWallet(address="0xabc123def456", label="Test Whale",
            chain="ethereum", copy_size_pct=10.0, max_copy_usd=200.0)
        with patch("copy_trade.copy_trade_agent.WalletWatcher") as MockWatcher:
            MockWatcher.return_value = AsyncMock()
            with patch("asyncio.create_task", return_value=MagicMock()):
                await agent.add_wallet(wallet)
        wallets = agent.list_wallets()
        assert len(wallets) == 1
        assert wallets[0]["label"] == "Test Whale"
        assert wallets[0]["copy_size_pct"] == 10.0

    @pytest.mark.asyncio
    async def test_copy_trade_rejected_on_low_safety(self):
        from copy_trade.copy_trade_agent import CopyTradeAgent
        from models.safety_schemas import SafetyReport, RiskLevel
        agent = CopyTradeAgent()
        emitted_events = []
        low_score_report = SafetyReport(contract_address="0xrug", chain="ethereum",
            safety_score=25, risk_level=RiskLevel.HIGH, is_honeypot=False,
            warnings=["Blacklist detected"], summary="Risky", recommendation="AVOID")
        async def capture_emit(event, payload):
            emitted_events.append((event, payload))
        with patch("copy_trade.copy_trade_agent.quick_scan", AsyncMock(return_value=low_score_report)), \
             patch("copy_trade.copy_trade_agent.bus.emit", side_effect=capture_emit):
            await agent._handle_copy_trade_request({"contract_address": "0xrug",
                "chain": "ethereum", "copy_amount_usd": 100, "safety_min_score": 60, "notify_only": False})
        from events.event_bus import Event
        emitted_event_types = [e[0] for e in emitted_events]
        assert Event.TRADE_REQUEST not in emitted_event_types
        assert Event.ALPHA_FOUND in emitted_event_types