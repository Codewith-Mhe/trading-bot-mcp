"""
safety/scanner.py
==================
Safety Scanner — the brain of Role 3's trade-gating system.

Runs GoPlus + Honeypot.is + TokenSniffer in PARALLEL (asyncio.gather).
Total scan time: ~1.5 seconds (limited by slowest API, not their sum).

Two scan modes:
  quick_scan()  — 3 seconds max, used for FOMO snipes (GoPlus + Honeypot only)
  full_scan()   — 10 seconds max, adds TokenSniffer + RugCheck (Solana)

Event Bus integration:
  Listens on: TRADE_REQUEST
  Emits on:   SAFETY_RESULT

MCP Tool:
  Also exposed as an MCP tool so the Research/Strategy Agent
  can request safety checks directly.
"""

from __future__ import annotations
import asyncio
import logging
import time
from mcp.server.fastmcp import FastMCP

from models.safety_schemas import SafetyReport, RiskLevel
from utils.token_cache import token_cache, CachedTokenScan
from events.event_bus import bus, Event
from safety.goplus import scan_goplus
from safety.honeypot import scan_honeypot
from safety.tokensniffer import scan_tokensniffer
from safety.rugcheck import scan_rugcheck

logger = logging.getLogger(__name__)

mcp = FastMCP("safety-scanner")


# ── Score Calculator ──────────────────────────────────────────────────────

def _calculate_score(gp, hp, ts) -> tuple[int, list[str]]:
    """
    Weighted composite safety score: 0 (dangerous) → 100 (clean).

    Weighting:
      GoPlus critical flags  → up to -50 points each
      Honeypot confirmation  → instant 0
      Sell tax               → up to -25
      TokenSniffer score     → 20% weight
      LP locked              → +10 bonus
    """
    warnings: list[str] = []
    score = 100

    # ── Critical deductions (trade-blocking) ─────────────────────────────
    if hp.is_honeypot or gp.is_honeypot:
        warnings.append("🚫 HONEYPOT: Cannot sell this token")
        return 0, warnings

    if gp.has_blacklist:
        score -= 30
        warnings.append("⛔ Blacklist function — deployer can block your wallet")

    if gp.has_mint_function:
        score -= 20
        warnings.append("⚠️ Mintable — supply can be inflated, diluting your position")

    if gp.has_hidden_owner:
        score -= 25
        warnings.append("⚠️ Hidden owner — contract has undisclosed admin")

    if gp.has_pause_function:
        score -= 20
        warnings.append("⚠️ Pausable — trading can be frozen by deployer")

    if gp.is_proxy:
        score -= 10
        warnings.append("⚠️ Proxy contract — logic can be upgraded by deployer")

    # ── Tax deductions ────────────────────────────────────────────────────
    sell_tax = max(gp.sell_tax_pct, hp.sell_tax_pct)
    buy_tax = max(gp.buy_tax_pct, hp.buy_tax_pct)

    if sell_tax > 30:
        score -= 25
        warnings.append(f"🔴 Very high sell tax: {sell_tax:.1f}%")
    elif sell_tax > 10:
        score -= 15
        warnings.append(f"🟡 High sell tax: {sell_tax:.1f}%")
    elif sell_tax > 5:
        score -= 5
        warnings.append(f"Sell tax: {sell_tax:.1f}%")

    if buy_tax > 10:
        score -= 10
        warnings.append(f"🟡 High buy tax: {buy_tax:.1f}%")

    # ── Holder concentration ──────────────────────────────────────────────
    if gp.top_10_holder_pct > 80:
        score -= 20
        warnings.append(f"🔴 Top 10 wallets hold {gp.top_10_holder_pct:.0f}% of supply — extreme dump risk")
    elif gp.top_10_holder_pct > 50:
        score -= 10
        warnings.append(f"🟡 Top 10 wallets hold {gp.top_10_holder_pct:.0f}% of supply")

    # ── LP lock ───────────────────────────────────────────────────────────
    if gp.lp_locked_pct < 50:
        score -= 10
        warnings.append(f"🟡 LP {gp.lp_locked_pct:.0f}% locked — rug pull risk")
    elif gp.lp_locked_pct >= 90:
        score += 5   # small bonus for well-locked LP
        score = min(score, 100)

    # ── TokenSniffer clone detection ──────────────────────────────────────
    if ts.is_copy and ts.similar_tokens > 3:
        score -= 15
        warnings.append(f"🟡 Token clone detected — {ts.similar_tokens} similar tokens found")

    if ts.deployer_previous_scams > 0:
        score -= 20
        warnings.append(f"🔴 Deployer has {ts.deployer_previous_scams} previous scam(s)")

    # ── TokenSniffer score blend (20% weight) ────────────────────────────
    if ts.score > 0:
        ts_contribution = (ts.score - 50) * 0.2
        score += int(ts_contribution)

    return max(0, min(100, score)), warnings


def _risk_level(score: int, is_honeypot: bool) -> RiskLevel:
    if is_honeypot:
        return RiskLevel.CRITICAL
    if score >= 80:
        return RiskLevel.SAFE
    if score >= 60:
        return RiskLevel.LOW
    if score >= 40:
        return RiskLevel.MEDIUM
    if score >= 20:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _recommendation(score: int, is_honeypot: bool, warnings: list[str]) -> str:
    if is_honeypot:
        return "AVOID — HONEYPOT DETECTED. You will not be able to sell."
    if score >= 75:
        return "SAFE TO BUY — No major red flags detected."
    if score >= 50:
        warn_count = len(warnings)
        return f"PROCEED WITH CAUTION — {warn_count} warning(s). Review before buying."
    return f"AVOID — Safety score {score}/100. High risk of loss."


# ── Core Scan Functions ───────────────────────────────────────────────────

async def quick_scan(contract_address: str, chain: str = "ethereum") -> SafetyReport:
    """
    Fast safety check — 3 seconds max.
    Runs GoPlus + Honeypot.is in parallel.
    Used for FOMO snipes where speed matters.
    """
    # Check token cache first
    cached = token_cache.get(chain, contract_address)
    if cached:
        logger.info("Safety cache HIT for %s (age: %.0fs)", contract_address[:10], cached.age_seconds())
        return _build_report_from_cache(cached)

    t0 = time.time()

    gp, hp = await asyncio.gather(
        scan_goplus(contract_address, chain),
        scan_honeypot(contract_address, chain),
    )

    # Neutral TokenSniffer for quick mode
    from models.safety_schemas import TokenSnifferResult
    ts = TokenSnifferResult(score=50)

    score, warnings = _calculate_score(gp, hp, ts)
    is_hp = gp.is_honeypot or hp.is_honeypot
    risk = _risk_level(score, is_hp)
    recommendation = _recommendation(score, is_hp, warnings)

    duration_ms = int((time.time() - t0) * 1000)

    report = SafetyReport(
        contract_address=contract_address,
        chain=chain,
        safety_score=score,
        risk_level=risk,
        is_honeypot=is_hp,
        has_mint_function=gp.has_mint_function,
        has_blacklist=gp.has_blacklist,
        trading_paused=gp.has_pause_function,
        high_buy_tax=max(gp.buy_tax_pct, hp.buy_tax_pct) > 10,
        high_sell_tax=max(gp.sell_tax_pct, hp.sell_tax_pct) > 10,
        lp_unlocked=gp.lp_locked_pct < 50,
        high_holder_concentration=gp.top_10_holder_pct > 50,
        buy_tax_pct=max(gp.buy_tax_pct, hp.buy_tax_pct),
        sell_tax_pct=max(gp.sell_tax_pct, hp.sell_tax_pct),
        lp_locked_pct=gp.lp_locked_pct,
        top_10_holder_pct=gp.top_10_holder_pct,
        warnings=warnings,
        summary=f"Safety: {score}/100 | {'HONEYPOT' if is_hp else risk.name} | Sell tax: {max(gp.sell_tax_pct, hp.sell_tax_pct):.1f}%",
        recommendation=recommendation,
        goplus=gp,
        honeypot=hp,
        scan_duration_ms=duration_ms,
        from_cache=False,
    )

    # Cache the result
    token_cache.set(CachedTokenScan(
        contract_address=contract_address,
        chain=chain,
        safety_score=score,
        is_honeypot=is_hp,
        warnings=warnings,
        raw_goplus=gp.raw,
        raw_tokensniffer={},
        raw_honeypot=hp.raw,
    ))

    logger.info(
        "Quick scan complete: %s | Score: %d/100 | %s | %dms",
        contract_address[:10], score, risk.name, duration_ms
    )
    return report


async def full_scan(contract_address: str, chain: str = "ethereum") -> SafetyReport:
    """
    Full safety check — up to 10 seconds.
    Runs GoPlus + Honeypot.is + TokenSniffer in parallel.
    Adds RugCheck for Solana tokens.
    Used for non-urgent trades where thoroughness matters more than speed.
    """
    cached = token_cache.get(chain, contract_address)
    if cached:
        logger.info("Safety cache HIT (full) for %s", contract_address[:10])
        return _build_report_from_cache(cached)

    t0 = time.time()

    if chain.lower() in ("solana", "sol"):
        gp, hp, ts, rc = await asyncio.gather(
            scan_goplus(contract_address, chain),
            scan_honeypot(contract_address, chain),
            scan_tokensniffer(contract_address, chain),
            scan_rugcheck(contract_address),
        )
    else:
        gp, hp, ts = await asyncio.gather(
            scan_goplus(contract_address, chain),
            scan_honeypot(contract_address, chain),
            scan_tokensniffer(contract_address, chain),
        )
        rc = None

    score, warnings = _calculate_score(gp, hp, ts)

    # Supplement with RugCheck data for Solana
    if rc and not rc.get("error"):
        if rc.get("risks"):
            warnings.extend([f"RugCheck: {r}" for r in rc["risks"][:3]])
        if not rc.get("mint_authority_disabled"):
            score = max(0, score - 15)
            warnings.append("⚠️ Mint authority still enabled (Solana)")

    is_hp = gp.is_honeypot or hp.is_honeypot
    risk = _risk_level(score, is_hp)
    recommendation = _recommendation(score, is_hp, warnings)
    duration_ms = int((time.time() - t0) * 1000)

    report = SafetyReport(
        contract_address=contract_address,
        chain=chain,
        safety_score=score,
        risk_level=risk,
        is_honeypot=is_hp,
        has_mint_function=gp.has_mint_function,
        has_blacklist=gp.has_blacklist,
        trading_paused=gp.has_pause_function,
        high_buy_tax=max(gp.buy_tax_pct, hp.buy_tax_pct) > 10,
        high_sell_tax=max(gp.sell_tax_pct, hp.sell_tax_pct) > 10,
        lp_unlocked=gp.lp_locked_pct < 50,
        high_holder_concentration=gp.top_10_holder_pct > 50,
        is_token_clone=ts.is_copy,
        buy_tax_pct=max(gp.buy_tax_pct, hp.buy_tax_pct),
        sell_tax_pct=max(gp.sell_tax_pct, hp.sell_tax_pct),
        lp_locked_pct=gp.lp_locked_pct,
        top_10_holder_pct=gp.top_10_holder_pct,
        warnings=warnings,
        summary=f"Safety: {score}/100 | {risk.name} | Buy tax: {max(gp.buy_tax_pct, hp.buy_tax_pct):.1f}% | Sell tax: {max(gp.sell_tax_pct, hp.sell_tax_pct):.1f}%",
        recommendation=recommendation,
        goplus=gp,
        tokensniffer=ts,
        honeypot=hp,
        scan_duration_ms=duration_ms,
        from_cache=False,
    )

    token_cache.set(CachedTokenScan(
        contract_address=contract_address,
        chain=chain,
        safety_score=score,
        is_honeypot=is_hp,
        warnings=warnings,
        raw_goplus=gp.raw,
        raw_tokensniffer=ts.raw,
        raw_honeypot=hp.raw,
    ))

    logger.info(
        "Full scan complete: %s | Score: %d/100 | %s | %dms",
        contract_address[:10], score, risk.name, duration_ms
    )
    return report


def _build_report_from_cache(cached: CachedTokenScan) -> SafetyReport:
    risk = _risk_level(cached.safety_score, cached.is_honeypot)
    return SafetyReport(
        contract_address=cached.contract_address,
        chain=cached.chain,
        safety_score=cached.safety_score,
        risk_level=risk,
        is_honeypot=cached.is_honeypot,
        warnings=cached.warnings,
        summary=f"[CACHED] Safety: {cached.safety_score}/100 | {risk.name}",
        recommendation=_recommendation(cached.safety_score, cached.is_honeypot, cached.warnings),
        from_cache=True,
        scan_duration_ms=0,
    )


# ── Event Bus Integration ─────────────────────────────────────────────────

@bus.on(Event.TRADE_REQUEST)
async def handle_trade_request(payload: dict) -> None:
    """
    Listen for TRADE_REQUEST events from the Intent Parser / Gateway.
    Run parallel safety scan and emit SAFETY_RESULT.

    Payload shape (from Role 1's intent parser):
    {
        "contract_address": "0x...",
        "chain": "ethereum",
        "urgency": "snipe" | "normal" | "safe",
        "amount_usd": 200,
        "user_id": "telegram:123456"
    }
    """
    ca = payload.get("contract_address")
    chain = payload.get("chain", "ethereum")
    urgency = payload.get("urgency", "normal")

    if not ca:
        logger.warning("TRADE_REQUEST received without contract_address — skipping safety scan")
        return

    logger.info("🔍 Safety scan triggered: %s on %s (urgency: %s)", ca[:10], chain, urgency)

    try:
        # Snipe mode = quick scan (3s max). Normal/safe = full scan (10s max).
        if urgency == "snipe":
            report = await quick_scan(ca, chain)
        else:
            report = await full_scan(ca, chain)

        # Emit result back onto the event bus for Strategy Agent to consume
        await bus.emit(Event.SAFETY_RESULT, {
            **report.model_dump(),
            # Pass through original payload context
            "original_request": payload,
        })

    except Exception as exc:
        logger.error("Safety scan failed for %s: %s", ca[:10], exc)
        # Emit a failed result so Strategy Agent doesn't hang waiting
        await bus.emit(Event.SAFETY_RESULT, {
            "contract_address": ca,
            "chain": chain,
            "safety_score": 0,
            "risk_level": 4,
            "is_honeypot": False,
            "warnings": [f"Safety scan error: {exc}"],
            "recommendation": "PROCEED WITH CAUTION — safety scan failed",
            "original_request": payload,
            "error": str(exc),
        })


# ── MCP Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def check_token_safety_quick(
    contract_address: str,
    chain: str = "ethereum",
) -> dict:
    """
    Fast token safety check — runs in under 3 seconds.
    Uses GoPlus + Honeypot.is in parallel.
    Returns safety score (0-100), honeypot flag, tax rates, and key warnings.
    Use this for time-sensitive snipe decisions.
    Chain options: ethereum, base, arbitrum, bsc, polygon, solana.
    """
    report = await quick_scan(contract_address, chain)
    return report.model_dump()


@mcp.tool()
async def check_token_safety_full(
    contract_address: str,
    chain: str = "ethereum",
) -> dict:
    """
    Full token safety check — runs in under 10 seconds.
    Uses GoPlus + Honeypot.is + TokenSniffer in parallel.
    Adds RugCheck for Solana tokens.
    Returns comprehensive safety score, all risk flags, and detailed warnings.
    Use before any non-urgent trade for maximum due diligence.
    Chain options: ethereum, base, arbitrum, bsc, polygon, solana.
    """
    report = await full_scan(contract_address, chain)
    return report.model_dump()


@mcp.tool()
async def get_token_safety_cached(
    contract_address: str,
    chain: str = "ethereum",
) -> dict:
    """
    Return cached safety scan result for a token if available (within 5 minutes).
    Returns null/empty if not in cache — call check_token_safety_quick first.
    Use to avoid redundant API calls when the same token is referenced multiple times.
    """
    cached = token_cache.get(chain, contract_address)
    if not cached:
        return {"cached": False, "contract_address": contract_address, "chain": chain}
    return {
        "cached": True,
        "age_seconds": cached.age_seconds(),
        "contract_address": contract_address,
        "chain": chain,
        "safety_score": cached.safety_score,
        "is_honeypot": cached.is_honeypot,
        "warnings": cached.warnings,
    }


@mcp.tool()
async def batch_safety_scan(
    contract_addresses: list[str],
    chain: str = "ethereum",
) -> list[dict]:
    """
    Run quick safety scans on multiple contract addresses simultaneously.
    All addresses scanned in parallel — total time = time of slowest single scan.
    Maximum 10 addresses per batch.
    Use when comparing multiple tokens or scanning a watchlist.
    """
    addresses = contract_addresses[:10]  # cap at 10
    reports = await asyncio.gather(
        *[quick_scan(ca, chain) for ca in addresses],
        return_exceptions=True,
    )
    results = []
    for ca, report in zip(addresses, reports):
        if isinstance(report, Exception):
            results.append({"contract_address": ca, "error": str(report)})
        else:
            results.append(report.model_dump())
    return results


# ── Entry point (standalone mode) ─────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    mcp.run()
