"""
test_server.py
==============
Simple test script to verify all tools are importable and working.
Run: uv run python test_server.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    print("=" * 55)
    print("  DeFi MCP Server — Tool Verification Test")
    print("=" * 55)

    # Test 1: DeFiLlama
    print("\n[1/5] Testing DeFiLlama...")
    try:
        from servers.defillama_server import get_top_yields
        result = await get_top_yields(min_tvl_usd=1_000_000, limit=3)
        print(f"  PASS — got {len(result)} yield pools")
        if result:
            print(f"  Top pool: {result[0]['protocol']} | {result[0]['symbol']} | APY: {result[0]['apy']:.2f}%")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 2: DexScreener
    print("\n[2/5] Testing DexScreener...")
    try:
        from servers.dexscreener_server import search_token_pairs
        result = await search_token_pairs("ETH", limit=3)
        print(f"  PASS — got {len(result)} pairs")
        if result:
            print(f"  Top pair: {result[0]['base_token_symbol']}/{result[0]['quote_token_symbol']} | Price: ${result[0]['price_usd']:.4f}")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 3: CoinGecko
    print("\n[3/5] Testing CoinGecko...")
    try:
        from servers.coingecko_server import get_global_market
        result = await get_global_market()
        print(f"  PASS — global market data received")
        if result.get("total_market_cap_usd"):
            print(f"  Total market cap: ${result['total_market_cap_usd']:,.0f}")
        if result.get("btc_dominance_pct"):
            print(f"  BTC dominance: {result['btc_dominance_pct']:.1f}%")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 4: Safety Scanner (no API call — uses scoring logic only)
    print("\n[4/5] Testing Safety Scanner (scoring logic)...")
    try:
        from safety.scanner import _calculate_score, _risk_level
        from models.safety_schemas import GoPlusResult, HoneypotResult, TokenSnifferResult
        gp = GoPlusResult(lp_locked_pct=90, top_10_holder_pct=25)
        hp = HoneypotResult(simulation_success=True)
        ts = TokenSnifferResult(score=80)
        score, warnings = _calculate_score(gp, hp, ts)
        risk = _risk_level(score, False)
        print(f"  PASS — scoring engine works")
        print(f"  Sample score: {score}/100 | Risk: {risk.name}")
    except Exception as e:
        print(f"  FAIL — {e}")

    # Test 5: Event Bus
    print("\n[5/5] Testing Event Bus...")
    try:
        from events.event_bus import EventBus, Event
        bus = EventBus()
        received = []
        @bus.on(Event.SAFETY_RESULT)
        async def handler(payload):
            received.append(payload)
        await bus.emit(Event.SAFETY_RESULT, {"safety_score": 85, "chain": "ethereum"})
        assert len(received) == 1
        print(f"  PASS — event emitted and received correctly")
        print(f"  Payload received: safety_score={received[0]['safety_score']}")
    except Exception as e:
        print(f"  FAIL — {e}")

    print("\n" + "=" * 55)
    print("  Verification complete.")
    print("  If all 5 passed, your Role 3 server is fully working.")
    print("=" * 55)

if __name__ == "__main__":
    asyncio.run(main())