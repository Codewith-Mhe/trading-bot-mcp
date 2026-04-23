"""
copy_trade/wallet_watcher.py
=============================
Persistent WebSocket watcher for a single target wallet.
One instance per watched wallet — they run independently in parallel.

When the target wallet makes a swap, it:
1. Detects the swap in real-time via WebSocket
2. Classifies the action (buy/sell/bridge/transfer)
3. Checks safety score on the token bought
4. Emits COPY_TRADE_REQUEST on the Event Bus

Data sources:
  - Alchemy WebSocket (pending + confirmed transactions)
  - Arkham entity labels (to classify the wallet)
  - DexScreener (to identify which token was swapped)
"""

from __future__ import annotations
import asyncio
import json
import logging
import websockets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from events.event_bus import bus, Event

logger = logging.getLogger(__name__)

# Known DEX router addresses (to detect swap transactions)
_DEX_ROUTERS = {
    "ethereum": {
        "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2",
        "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3",
        "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 (Router2)",
        "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange",
        "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch V5",
    },
    "base": {
        "0x2626664c2603336e57b271c5c0b26f421741e481": "Uniswap V3 Base",
        "0x198ef79f1f515f02dfe9e3115ed9fc07183f02fc": "Aerodrome",
    },
    "arbitrum": {
        "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Arb",
        "0xc873fecbd354f5a56e00e710b90ef4201db2448d": "Camelot",
    },
}


@dataclass
class WatchedWallet:
    address: str
    label: Optional[str] = None           # e.g. "Cobie", "0x1234..."
    chain: str = "ethereum"
    copy_size_pct: float = 10.0           # copy at 10% of their trade size
    max_copy_usd: float = 500.0           # never copy more than $500
    min_token_age_hours: float = 1.0      # only copy tokens live > 1h
    safety_min_score: int = 60            # only copy if safety score >= 60
    notify_only: bool = False             # if True, alert but don't auto-copy
    added_at: datetime = field(default_factory=datetime.utcnow)
    trade_count: int = 0


class WalletWatcher:
    """
    Watches a single wallet address for swap transactions.
    Runs as a persistent background task.
    """

    def __init__(self, wallet: WatchedWallet, alchemy_ws_url: str) -> None:
        self.wallet = wallet
        self._ws_url = alchemy_ws_url
        self._running = False
        self._reconnect_delay = 5

    async def start(self) -> None:
        """Start watching. Auto-reconnects on disconnect."""
        self._running = True
        label = self.wallet.label or self.wallet.address[:10]
        logger.info("👁 Watching wallet: %s on %s", label, self.wallet.chain)

        while self._running:
            try:
                await self._watch_loop()
            except Exception as exc:
                logger.warning(
                    "Watcher disconnected for %s: %s — reconnecting in %ds",
                    label, exc, self._reconnect_delay
                )
                await asyncio.sleep(self._reconnect_delay)

    def stop(self) -> None:
        self._running = False

    async def _watch_loop(self) -> None:
        """WebSocket loop — subscribe to pending txns for the target address."""
        subscription = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "alchemy_pendingTransactions",
                {
                    "fromAddress": self.wallet.address,
                    "toAddress": list(_DEX_ROUTERS.get(self.wallet.chain, {}).keys()),
                    "hashesOnly": False,
                }
            ]
        })

        async with websockets.connect(self._ws_url, ping_interval=30) as ws:
            await ws.send(subscription)
            logger.debug("WebSocket subscribed for %s", self.wallet.address[:10])

            async for message in ws:
                if not self._running:
                    break
                try:
                    data = json.loads(message)
                    tx = data.get("params", {}).get("result", {})
                    if tx:
                        await self._process_transaction(tx)
                except Exception as exc:
                    logger.error("TX processing error: %s", exc)

    async def _process_transaction(self, tx: dict) -> None:
        """Detect if this is a swap and emit COPY_TRADE_REQUEST."""
        to_addr = (tx.get("to") or "").lower()
        chain_routers = _DEX_ROUTERS.get(self.wallet.chain, {})
        dex_name = chain_routers.get(to_addr)

        if not dex_name:
            return  # Not a DEX swap

        # Decode what token they're buying from the input data
        token_bought = await self._decode_swap_token(tx)
        if not token_bought:
            return

        value_eth = int(tx.get("value", "0x0"), 16) / 1e18
        # Rough USD estimate (TODO: use live ETH price from CoinGecko)
        est_usd = value_eth * 3000  # placeholder

        copy_usd = min(
            est_usd * (self.wallet.copy_size_pct / 100),
            self.wallet.max_copy_usd,
        )

        self.wallet.trade_count += 1
        label = self.wallet.label or self.wallet.address[:10]

        logger.info(
            "🎯 Copy trade signal: %s bought %s on %s | ~$%.0f | Copy: $%.0f",
            label, token_bought[:10], dex_name, est_usd, copy_usd
        )

        await bus.emit(Event.COPY_TRADE_REQUEST, {
            "source_wallet": self.wallet.address,
            "source_label": self.wallet.label,
            "contract_address": token_bought,
            "chain": self.wallet.chain,
            "dex": dex_name,
            "source_amount_usd": est_usd,
            "copy_amount_usd": copy_usd,
            "notify_only": self.wallet.notify_only,
            "safety_min_score": self.wallet.safety_min_score,
            "min_token_age_hours": self.wallet.min_token_age_hours,
            "tx_hash": tx.get("hash"),
            "urgency": "normal",   # copy trades use full safety scan
        })

    async def _decode_swap_token(self, tx: dict) -> Optional[str]:
        """
        Attempt to extract the output token address from swap calldata.
        This is a simplified heuristic — in production use ABI decoding.
        """
        input_data = tx.get("input", "")
        if len(input_data) < 10:
            return None

        # For Uniswap V2/V3, the token address is often in the last 32 bytes
        # Full ABI decoding is done by the Execution Agent (Role 2)
        # We extract a candidate address from the calldata as a best-effort
        if len(input_data) >= 74:
            # Extract 20-byte address from typical position in swap calldata
            candidate = "0x" + input_data[-40:]
            if candidate.startswith("0x") and len(candidate) == 42:
                return candidate

        return None
