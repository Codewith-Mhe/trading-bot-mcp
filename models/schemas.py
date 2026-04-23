"""
models/schemas.py
=================
Single source of truth for all data shapes in the system.
Every MCP tool returns data normalized to these models.
Agents never need to know which API a data point came from.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Token / Market ────────────────────────────────────────────────────────

class TokenData(BaseModel):
    symbol: str
    name: str
    price_usd: float
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    price_change_24h_pct: Optional[float] = None
    price_change_7d_pct: Optional[float] = None
    circulating_supply: Optional[float] = None
    source: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ── Protocol / TVL ────────────────────────────────────────────────────────

class ProtocolTVL(BaseModel):
    protocol: str
    tvl_usd: float
    tvl_by_chain: Optional[dict[str, float]] = None
    change_1d_pct: Optional[float] = None
    change_7d_pct: Optional[float] = None
    category: Optional[str] = None
    chains: Optional[list[str]] = None
    source: str = "defillama"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ── Yield Pool ────────────────────────────────────────────────────────────

class YieldPool(BaseModel):
    pool_id: str
    protocol: str
    chain: str
    symbol: str
    apy: float
    apy_base: Optional[float] = None
    apy_reward: Optional[float] = None
    tvl_usd: Optional[float] = None
    stable_coin: bool = False
    il_risk: Optional[str] = None      # "no" | "low" | "medium" | "high"
    outlook: Optional[str] = None      # "stable" | "up" | "down"
    source: str = "defillama"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ── DEX Pair ──────────────────────────────────────────────────────────────

class DexPair(BaseModel):
    pair_address: str
    base_token_symbol: str
    quote_token_symbol: str
    price_usd: float
    price_native: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    price_change_5m_pct: Optional[float] = None
    price_change_1h_pct: Optional[float] = None
    price_change_24h_pct: Optional[float] = None
    txns_24h_buys: Optional[int] = None
    txns_24h_sells: Optional[int] = None
    dex_name: Optional[str] = None
    chain: Optional[str] = None
    fdv: Optional[float] = None
    source: str = "dexscreener"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ── Whale Transaction ─────────────────────────────────────────────────────

class WhaleTransaction(BaseModel):
    tx_hash: Optional[str] = None
    wallet_address: str
    wallet_label: Optional[str] = None
    token_symbol: str
    amount_usd: float
    amount_tokens: Optional[float] = None
    action: str                            # "buy" | "sell" | "transfer" | "bridge"
    chain: str
    protocol: Optional[str] = None
    source: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Alert ─────────────────────────────────────────────────────────────────

class Alert(BaseModel):
    alert_id: str
    alert_type: str     # "price_spike" | "tvl_drop" | "whale_move" | "dex_anomaly"
    severity: str       # "info" | "warning" | "critical"
    title: str
    description: str
    data: dict
    triggered_at: datetime = Field(default_factory=datetime.utcnow)


# ── Global Market Overview ────────────────────────────────────────────────

class GlobalMarket(BaseModel):
    total_market_cap_usd: Optional[float] = None
    total_volume_24h_usd: Optional[float] = None
    market_cap_change_24h_pct: Optional[float] = None
    btc_dominance_pct: Optional[float] = None
    eth_dominance_pct: Optional[float] = None
    active_cryptocurrencies: Optional[int] = None
    fear_greed_value: Optional[int] = None
    fear_greed_label: Optional[str] = None
    source: str = "coingecko"
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ── Aggregated Snapshot ───────────────────────────────────────────────────

class MarketSnapshot(BaseModel):
    """
    The primary object the Strategy Agent consumes.
    Combines all data sources into one complete market picture.
    """
    global_market: Optional[GlobalMarket] = None
    top_tokens: list[TokenData] = []
    top_yields: list[YieldPool] = []
    trending_pairs: list[DexPair] = []
    recent_whale_moves: list[WhaleTransaction] = []
    active_alerts: list[Alert] = []
    chain: str = "ethereum"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
