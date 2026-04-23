# DeFi MCP Tool Server — Role 3

Real-time DeFi market data backbone for the multi-agent trading system.  
Built with **FastMCP** (the current standard) — 22 tools, 5 live resources, 4 agent prompts.

---

## Architecture

```
defi-mcp/
├── main_server.py              ← unified FastMCP server (run this)
├── servers/
│   ├── defillama_server.py     ← 6 tools: TVL, yields, fees, stablecoins
│   ├── dexscreener_server.py   ← 5 tools: pair search, gainers, new pairs
│   ├── coingecko_server.py     ← 7 tools: markets, sentiment, fear/greed
│   └── whale_tracker_server.py ← 5 tools: whale txns, wallet profiles, flows
├── resources/
│   └── live_resources.py       ← 5 MCP resources (live data feeds for agents)
├── prompts/
│   └── analysis_prompts.py     ← 4 reusable agent analysis templates
├── aggregator/
│   └── aggregator.py           ← parallel data merge → MarketSnapshot
├── alerts/
│   ├── alert_engine.py         ← price spike / whale / DEX anomaly detection
│   └── monitor.py              ← real-time polling loop + handler dispatch
├── models/
│   └── schemas.py              ← unified Pydantic schemas (single source of truth)
├── utils/
│   ├── http_client.py          ← async HTTP + TTL cache + retry
│   └── ollama_client.py        ← local LLM analysis via Ollama
├── config/
│   └── settings.py             ← pydantic-settings (auto-loads .env)
├── tests/
│   └── test_servers.py         ← full pytest test suite
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml              ← modern Python project config (uv-compatible)
```

---

## Quick Start

### 1. Install with uv (recommended)
```bash
# Install uv if you don't have it
curl -Ls https://astral.sh/uv/install.sh | sh

# Install all dependencies
uv sync

# Or with plain pip:
pip install -e ".[dev]"
```

### 2. Configure API keys
```bash
cp .env.example .env
# Open .env and fill in your keys (see table below)
```

| Key | Where to get it | Cost |
|-----|----------------|------|
| `COINGECKO_API_KEY` | https://coingecko.com/en/api | Free |
| `ARKHAM_API_KEY` | https://docs.arkhamintelligence.com | Apply |
| `NANSEN_API_KEY` | https://nansen.ai/api | Apply (fallback) |

DeFiLlama and DexScreener are **free with no key required**.

### 3. Set your Ollama model
```bash
ollama list                # see installed models
ollama pull llama3         # pull if not installed
# Set OLLAMA_MODEL=llama3 in your .env
```

### 4. Run the server
```bash
# Local agents (stdio — default)
python main_server.py

# Remote agents (HTTP)
python main_server.py --http

# Test with MCP Inspector UI
python main_server.py --inspect
```

### 5. Run the real-time monitor (separate terminal)
```bash
python alerts/monitor.py
```

### 6. Run tests
```bash
pytest tests/ -v
```

---

## All 22 Tools

### DeFiLlama (TVL & Yields)
| Tool | Description |
|------|-------------|
| `get_all_protocols` | All protocols + TVL, category, chains |
| `get_protocol_tvl` | Single protocol TVL + 24h/7d change |
| `get_chain_tvl` | Full chain TVL + 24h change |
| `get_top_yields` | Best yield pools (filterable by chain, TVL, stables) |
| `get_stablecoin_overview` | Peg health + chain distribution |
| `get_protocol_fees` | Protocol fee/revenue data |

### DexScreener (DEX Prices & Liquidity)
| Tool | Description |
|------|-------------|
| `search_token_pairs` | Find pairs by name/symbol, sorted by liquidity |
| `get_pair_by_address` | Real-time pair data by contract address |
| `get_token_all_pairs` | All DEX pools for a token address |
| `get_top_gainers` | Highest 24h movers (dust filtered) |
| `get_new_pairs` | Newest created pairs on a chain |

### CoinGecko (Market Data & Sentiment)
| Tool | Description |
|------|-------------|
| `get_top_markets` | Top coins by market cap with 24h/7d change |
| `get_coin_details` | Full due diligence: ATH, supply, sentiment, contracts |
| `get_trending_coins` | Top 7 trending by search volume |
| `get_global_market` | Total market cap, BTC/ETH dominance |
| `get_fear_and_greed` | Sentiment index 0-100 + history |
| `get_price_history` | Historical OHLC data (1-365 days) |
| `search_coins` | Find CoinGecko ID by name/symbol |

### Whale Tracker (Arkham / Nansen)
| Tool | Description |
|------|-------------|
| `get_whale_transactions` | Large txns above threshold (Nansen fallback) |
| `get_wallet_profile` | Full holdings + entity label for a wallet |
| `get_smart_money_flow` | Net accumulation/distribution for a token |
| `lookup_wallet_label` | Identify entity behind a wallet address |
| `get_exchange_flows` | CEX inflow/outflow (sell pressure indicator) |

---

## 5 Live Resources (MCP Resource Layer)

Resources are live data feeds agents can subscribe to without calling tools:

| URI | Description |
|-----|-------------|
| `defi://market/snapshot` | Full market snapshot (updated every 60s) |
| `defi://market/alerts` | Currently active alerts |
| `defi://market/fear-greed` | Current fear/greed value |
| `defi://chain/{chain}/tvl` | Live TVL for any chain |
| `defi://token/{symbol}/price` | Live token price by symbol |

---

## 4 Agent Prompts

Reusable instruction templates surfaced as slash-commands in MCP clients:

| Prompt | Use Case |
|--------|----------|
| `market_overview_prompt` | Full market analysis before any trade |
| `token_due_diligence_prompt` | Deep-dive on a specific token |
| `yield_strategy_prompt` | Find best yield opportunities |
| `whale_alert_analysis_prompt` | Investigate a whale transaction |

---

## Connecting to the Agent Layer (Role 1)

```python
# CrewAI / LangGraph — point MCP client at this server
from mcp import ClientSession, StdioServerParameters
import asyncio

server_params = StdioServerParameters(
    command="python",
    args=["path/to/defi-mcp/main_server.py"],
)

async def main():
    async with ClientSession(*server_params) as session:
        tools = await session.list_tools()
        result = await session.call_tool("get_top_markets", {"limit": 10})
```

---

## Connecting Alerts to Role 4 (Telegram / Discord)

In `alerts/monitor.py`, register your Role 4 handlers:

```python
from integrations.telegram import telegram_handler
from integrations.discord import discord_handler

monitor.register_handler(telegram_handler)
monitor.register_handler(discord_handler)
```

---

## Docker Deployment (for Role 5)

```bash
# Build and run everything
docker compose up --build

# MCP server available at http://localhost:8000
# Monitor running in background
# Ollama available at http://localhost:11434
```

---

## Safety Scanner (Gap 1 — Now Added)

Pre-trade safety scanning using **3 APIs in parallel** (GoPlus + Honeypot.is + TokenSniffer).

| API | What it checks | Key | Speed |
|-----|---------------|-----|-------|
| GoPlus | Mint, blacklist, hidden owner, tax, LP lock, holder % | Free | ~1s |
| Honeypot.is | Simulate sell before buying | Free | ~0.5s |
| TokenSniffer | Clone detection, deployer scam history | Paid | ~2s |
| RugCheck | Solana-specific: mint authority, freeze authority | Free | ~1s |

Total scan time (all 3 parallel): **~1.5 seconds**

```
check_token_safety_quick   → 3s max (GoPlus + Honeypot) — for snipes
check_token_safety_full    → 10s max (all 3 APIs) — for normal trades
batch_safety_scan          → scan up to 10 CAs simultaneously
get_token_safety_cached    → return cached result (5-min TTL per CA)
```

---

## Event Bus Integration (Gap 2 — Now Added)

Role 3 is fully wired into the agent Event Bus:

```
User pastes CA → Intent Parser → TRADE_REQUEST emitted
                                       ↓
                          Safety Agent listens (Role 3)
                          GoPlus + Honeypot + TokenSniffer (parallel)
                                       ↓
                          SAFETY_RESULT emitted → Strategy Agent
                                       ↓
                          If approved → EXECUTE_TRADE
```

Research Agent (monitor) also emits:
```
ALPHA_FOUND → Role 5 Gateway → Telegram/Discord push notification
```

---

## Copy Trade Agent (Gap 4 — Now Added)

```
watch_wallet     → start watching a wallet (one WebSocket per wallet)
unwatch_wallet   → stop watching
list_watched_wallets → see current watchlist

Filters applied before copying:
  safety_min_score  (default 60) — reject if safety scan below threshold
  min_token_age_hours             — avoid brand new tokens
  max_copy_usd                    — spending cap per copy trade
  notify_only                     — alert without auto-executing
```

---

## API Keys — Full List

| Key | Required | Where |
|-----|----------|-------|
| `COINGECKO_API_KEY` | Yes | https://coingecko.com/en/api |
| `ARKHAM_API_KEY` | Yes | https://docs.arkhamintelligence.com |
| `NANSEN_API_KEY` | Optional (fallback) | https://nansen.ai/api |
| `TOKENSNIFFER_API_KEY` | Optional (fallback to 50/100 score) | https://tokensniffer.com |
| `ALCHEMY_WS_URL` | Yes (copy trade) | https://alchemy.com |

GoPlus, Honeypot.is, RugCheck, DeFiLlama, DexScreener = **free, no key needed**
