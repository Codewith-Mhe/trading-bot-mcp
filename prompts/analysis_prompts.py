"""
prompts/analysis_prompts.py
============================
MCP Prompts — reusable analysis templates the agent layer can invoke.
Prompts are pre-written instruction templates that surface as slash-commands
in MCP-compatible clients and as named prompts in the agent framework.
"""

from __future__ import annotations
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("defi-prompts")


@mcp.prompt()
def market_overview_prompt(chain: str = "ethereum") -> str:
    """
    Full market analysis prompt — instructs the agent to gather and synthesize
    a complete market overview for a given chain before making any recommendation.
    """
    return f"""
You are a DeFi market analyst. Perform a complete market overview for the {chain} ecosystem.

Follow this exact sequence:
1. Call `get_global_market` — assess overall market health and BTC/ETH dominance
2. Call `get_fear_and_greed` — establish current market sentiment
3. Call `get_top_markets` with limit=20 — identify top movers
4. Call `get_top_yields` filtered to {chain} — find yield opportunities
5. Call `get_top_gainers` for {chain} — identify momentum plays
6. Call `get_whale_transactions` for {chain} — check institutional activity

Then produce a structured report with these sections:
- **Market Sentiment**: Overall mood, fear/greed reading, macro context
- **Top Opportunities**: 2-3 specific actionable plays with rationale
- **Risk Flags**: Any concerning signals (whale dumps, liquidity issues, anomalies)
- **Recommended Stance**: aggressive / moderate / defensive, with one-line justification
"""


@mcp.prompt()
def token_due_diligence_prompt(token_symbol: str, chain: str = "ethereum") -> str:
    """
    Full due diligence template for a specific token before executing a trade.
    Instructs the agent to gather all relevant data points and assess risk/reward.
    """
    return f"""
Perform full due diligence on {token_symbol} before any trade recommendation.

Data gathering sequence:
1. Call `search_coins` with query="{token_symbol}" to get the CoinGecko ID
2. Call `get_coin_details` with that ID — full market and sentiment data
3. Call `search_token_pairs` with query="{token_symbol}" — DEX liquidity map
4. Call `get_smart_money_flow` for {token_symbol} over 24h — institutional signals
5. Call `get_whale_transactions` — check if whales are buying or selling
6. Call `get_price_history` for 30 days — trend analysis

Produce a due diligence report:
- **Asset Summary**: what it is, market cap, category, chain
- **Price Analysis**: recent trend, key support/resistance, 30d trajectory
- **Liquidity Assessment**: DEX depth, best venue to trade, slippage risk
- **Smart Money Signal**: net accumulation or distribution? Who?
- **Risk Score**: 1-10 with reasoning (consider: liquidity, volatility, whale concentration)
- **Trade Recommendation**: BUY / HOLD / AVOID with entry, target, and stop-loss levels
"""


@mcp.prompt()
def yield_strategy_prompt(
    min_apy: float = 10.0,
    risk_tolerance: str = "medium",
    chain: str = "",
) -> str:
    """
    Yield farming strategy prompt — finds and ranks yield opportunities
    based on APY, risk tolerance, and chain preference.
    """
    return f"""
Find the best yield farming opportunities matching these parameters:
- Minimum APY: {min_apy}%
- Risk tolerance: {risk_tolerance} (low=stables only, medium=major tokens, high=any)
- Chain preference: {chain if chain else "any chain"}

Data gathering:
1. Call `get_top_yields` with min_tvl_usd=500000, stable_only={risk_tolerance == "low"}{f", chain='{chain}'" if chain else ""}
2. For top 3 results, call `get_protocol_tvl` for each protocol — verify TVL stability
3. Call `get_stablecoin_overview` if any stablecoin pools are in the results — check peg health
4. Call `get_global_market` — assess whether current market conditions favour yield vs spot

Produce a yield strategy report:
- **Top 3 Recommended Pools**: ranked by risk-adjusted APY
- **Protocol Health**: TVL trend for each recommended protocol (growing/shrinking?)
- **IL Risk Assessment**: explain impermanent loss exposure per pool
- **Entry Timing**: is now a good time to enter, or wait for better conditions?
- **Exit Triggers**: what signals should prompt exiting each position?
"""


@mcp.prompt()
def whale_alert_analysis_prompt(wallet_address: str, token_symbol: str, amount_usd: float) -> str:
    """
    Whale alert analysis — when a large transaction is detected,
    this prompt instructs the agent to investigate and produce an actionable signal.
    """
    return f"""
A large whale transaction has been detected. Investigate and produce a trade signal.

Transaction: ${amount_usd:,.0f} of {token_symbol} from wallet {wallet_address}

Investigation sequence:
1. Call `lookup_wallet_label` for {wallet_address} — identify the entity
2. Call `get_wallet_profile` for {wallet_address} — what else do they hold?
3. Call `get_smart_money_flow` for {token_symbol} over 4h — is this isolated or part of a trend?
4. Call `search_token_pairs` for {token_symbol} — check if price has already moved
5. Call `get_coin_details` for {token_symbol} — market cap context

Produce a whale signal report:
- **Who is this wallet?** Known entity or anonymous? Track record?
- **Is this a signal?** Isolated move or part of broader trend?
- **Price Impact**: has the market priced this in yet?
- **Recommended Action**: BUY / SELL / WATCH with urgency level (immediate/hours/days)
- **Confidence Level**: high/medium/low with reasoning
"""
