"""
config/settings.py
==================
All configuration loaded automatically from environment variables or .env file.
Uses pydantic-settings — no manual os.getenv() calls needed anywhere else.

To configure: copy .env.example → .env and fill in your API keys.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── API Keys ──────────────────────────────────────────────────────────
    # Free key → https://www.coingecko.com/en/api
    coingecko_api_key: str = Field(default="", alias="COINGECKO_API_KEY")

    # Apply → https://docs.arkhamintelligence.com
    arkham_api_key: str = Field(default="", alias="ARKHAM_API_KEY")

    # Fallback whale tracker → https://www.nansen.ai/api
    nansen_api_key: str = Field(default="", alias="NANSEN_API_KEY")

    # ── Base URLs (no keys needed — leave as-is) ──────────────────────────
    defillama_base_url: str = "https://api.llama.fi"
    defillama_yields_url: str = "https://yields.llama.fi"
    dexscreener_base_url: str = "https://api.dexscreener.com/latest/dex"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    arkham_base_url: str = "https://api.arkhamintelligence.com"
    nansen_base_url: str = "https://api.nansen.ai"

    # ── Ollama (local — no key needed) ────────────────────────────────────
    # Run `ollama list` to see available models on your machine
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3", alias="OLLAMA_MODEL")
    ollama_embed_model: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBED_MODEL")

    # ── MCP Server ────────────────────────────────────────────────────────
    # Transport: "stdio" for local agents, "streamable-http" for remote
    mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    mcp_port: int = Field(default=8000, alias="MCP_PORT")

    # ── Alert Thresholds ──────────────────────────────────────────────────
    price_alert_pct: float = Field(default=5.0, alias="PRICE_ALERT_PCT")
    tvl_alert_pct: float = Field(default=10.0, alias="TVL_ALERT_PCT")
    whale_threshold_usd: float = Field(default=100_000.0, alias="WHALE_THRESHOLD_USD")

    # ── Safety APIs ───────────────────────────────────────────────────────
    # TokenSniffer clone/pattern detection — https://tokensniffer.com
    tokensniffer_api_key: str = Field(default="", alias="TOKENSNIFFER_API_KEY")

    # ── RPC / WebSocket ───────────────────────────────────────────────────
    # Alchemy WebSocket — for copy trade wallet watching
    # Get at: https://alchemy.com (free tier available)
    alchemy_ws_url: str = Field(
        default="wss://eth-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY",
        alias="ALCHEMY_WS_URL",
    )

    # ── Cache & Polling ───────────────────────────────────────────────────
    cache_ttl_seconds: int = Field(default=30, alias="CACHE_TTL_SECONDS")
    poll_interval_seconds: int = Field(default=60, alias="POLL_INTERVAL_SECONDS")


# Single shared instance — import this everywhere
settings = Settings()
