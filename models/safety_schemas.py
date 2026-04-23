"""
models/safety_schemas.py
=========================
Safety-specific data models + Alpha Signal models.
Consumed by the Safety Agent, Strategy Agent, and Research Agent (monitor).
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import IntEnum, Enum


class RiskLevel(IntEnum):
    SAFE     = 0
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4


class GoPlusResult(BaseModel):
    is_honeypot: bool = False
    has_mint_function: bool = False
    has_blacklist: bool = False
    has_pause_function: bool = False
    is_proxy: bool = False
    has_hidden_owner: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    lp_locked_pct: float = 0.0
    top_10_holder_pct: float = 0.0
    creator_balance_pct: float = 0.0
    is_open_source: bool = True
    trading_cooldown: bool = False
    transfer_pausable: bool = False
    raw: dict = Field(default_factory=dict)


class TokenSnifferResult(BaseModel):
    score: int = 0
    similar_tokens: int = 0
    is_copy: bool = False
    deployer_previous_scams: int = 0
    raw: dict = Field(default_factory=dict)


class HoneypotResult(BaseModel):
    is_honeypot: bool = False
    simulation_success: bool = False
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    transfer_tax_pct: float = 0.0
    buy_gas: Optional[int] = None
    sell_gas: Optional[int] = None
    reason: Optional[str] = None
    raw: dict = Field(default_factory=dict)


class SafetyReport(BaseModel):
    """
    Final aggregated safety report for a token.
    Emitted as SAFETY_RESULT on the Event Bus.
    Strategy Agent uses this to approve or reject a trade.
    """
    contract_address: str
    chain: str
    token_name: Optional[str] = None
    token_symbol: Optional[str] = None

    # Composite score: 0 = dangerous, 100 = clean
    safety_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel = RiskLevel.MEDIUM

    # Critical flags — any one of these = auto-reject
    is_honeypot: bool = False
    has_mint_function: bool = False
    has_blacklist: bool = False
    trading_paused: bool = False

    # Warning flags — show to user but don't auto-reject
    high_buy_tax: bool = False
    high_sell_tax: bool = False
    lp_unlocked: bool = False
    high_holder_concentration: bool = False
    is_token_clone: bool = False

    # Raw numbers
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    lp_locked_pct: float = 0.0
    top_10_holder_pct: float = 0.0

    # Human-readable output
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    recommendation: str = ""           # "SAFE TO BUY" | "PROCEED WITH CAUTION" | "AVOID"

    # Sub-results from each API
    goplus: Optional[GoPlusResult] = None
    tokensniffer: Optional[TokenSnifferResult] = None
    honeypot: Optional[HoneypotResult] = None

    # Meta
    scan_duration_ms: int = 0
    from_cache: bool = False
    scanned_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "safety-scanner"


# ── Event Types (used by Event Bus + Monitor) ─────────────────────────────

class EventType(str, Enum):
    """Mirrors events/event_bus.py Event enum — used in model typing."""
    TRADE_REQUEST      = "TRADE_REQUEST"
    SAFETY_RESULT      = "SAFETY_RESULT"
    ALPHA_FOUND        = "ALPHA_FOUND"
    COPY_TRADE_REQUEST = "COPY_TRADE_REQUEST"
    TRADE_EXECUTED     = "TRADE_EXECUTED"
    EXECUTE_SELL       = "EXECUTE_SELL"
    REJECT_TRADE       = "REJECT_TRADE"
    POSITION_UPDATE    = "POSITION_UPDATE"


# ── Alpha Signal (emitted by Research Agent → ALPHA_FOUND event) ──────────

class AlphaSignal(BaseModel):
    """
    Structured alpha signal emitted by the Research Agent.
    Picked up by Role 5 Gateway and delivered to user via Telegram/Discord.
    """
    signal_type: str          # "whale_accumulation" | "trending_new_pair" | "smart_money_buy"
    token_symbol: str
    token_address: Optional[str] = None
    chain: str
    description: str          # plain-English message sent to user
    amount_usd: Optional[float] = None
    source_wallet: Optional[str] = None
    source_wallet_label: Optional[str] = None
    confidence: str = "medium"   # "low" | "medium" | "high"
    raw_data: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
