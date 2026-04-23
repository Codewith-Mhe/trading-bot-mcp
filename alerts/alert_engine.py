"""
alerts/alert_engine.py
=======================
Detects market anomalies and fires structured Alert objects.
Alerts feed into the monitor loop, which dispatches them to
Role 4's Telegram/Discord/WebSocket notification handlers.
"""

from __future__ import annotations
import logging
from datetime import datetime
from models.schemas import Alert, TokenData, DexPair, WhaleTransaction
from config.settings import settings

logger = logging.getLogger(__name__)


class AlertEngine:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def evaluate(
        self,
        tokens: list[TokenData] = [],
        pairs: list[DexPair] = [],
        whales: list[WhaleTransaction] = [],
    ) -> list[Alert]:
        """Run all checks and return deduplicated new alerts."""
        raw: list[Alert] = []
        raw.extend(self._price_spikes(tokens))
        raw.extend(self._dex_anomalies(pairs))
        raw.extend(self._whale_moves(whales))

        new = [a for a in raw if a.alert_id not in self._seen]
        for a in new:
            self._seen.add(a.alert_id)
        if new:
            logger.info("🚨 %d new alert(s)", len(new))
        return new

    # ── Price Spikes ──────────────────────────────────────────────────────

    def _price_spikes(self, tokens: list[TokenData]) -> list[Alert]:
        alerts = []
        threshold = settings.price_alert_pct
        for t in tokens:
            pct = t.price_change_24h_pct
            if pct is None or abs(pct) < threshold:
                continue
            direction = "📈 PUMP" if pct > 0 else "📉 DUMP"
            severity = "critical" if abs(pct) >= threshold * 2 else "warning"
            alerts.append(Alert(
                alert_id=f"price:{t.symbol}:{datetime.utcnow().strftime('%Y%m%d')}",
                alert_type="price_spike",
                severity=severity,
                title=f"{direction}: {t.symbol} {pct:+.1f}% in 24h",
                description=(
                    f"{t.name} ({t.symbol}) moved {pct:+.2f}% in 24h. "
                    f"Price: ${t.price_usd:,.4f}."
                    + (f" Market cap: ${t.market_cap:,.0f}." if t.market_cap else "")
                ),
                data={"symbol": t.symbol, "price_usd": t.price_usd, "change_24h_pct": pct},
            ))
        return alerts

    # ── DEX Anomalies ─────────────────────────────────────────────────────

    def _dex_anomalies(self, pairs: list[DexPair]) -> list[Alert]:
        alerts = []
        for p in pairs:
            sym = f"{p.base_token_symbol}/{p.quote_token_symbol}"
            liq = p.liquidity_usd or 0
            vol = p.volume_24h_usd or 0

            # High volume vs thin liquidity — rug or pump risk
            if liq > 0 and vol > 0 and (vol / liq) > 5:
                alerts.append(Alert(
                    alert_id=f"dex_vol:{p.pair_address}:{datetime.utcnow().strftime('%Y%m%d')}",
                    alert_type="volume_liquidity_anomaly",
                    severity="warning",
                    title=f"⚠️ {sym} volume/liquidity ratio {vol/liq:.1f}x",
                    description=(
                        f"{sym} on {p.dex_name} ({p.chain}) has ${vol:,.0f} volume "
                        f"against only ${liq:,.0f} liquidity. Possible pump or rug."
                    ),
                    data={"pair": sym, "dex": p.dex_name, "chain": p.chain, "ratio": round(vol / liq, 2)},
                ))

            # Rapid 1h price move
            h1 = p.price_change_1h_pct or 0
            if abs(h1) >= 10:
                word = "spiked" if h1 > 0 else "crashed"
                alerts.append(Alert(
                    alert_id=f"dex_1h:{p.pair_address}:{datetime.utcnow().strftime('%Y%m%d%H')}",
                    alert_type="rapid_price_move",
                    severity="warning",
                    title=f"⚡ {sym} {word} {h1:+.1f}% in 1 hour",
                    description=f"{sym} on {p.dex_name} ({p.chain}): {word} {h1:+.2f}% in 1h. Price: ${p.price_usd:,.6f}.",
                    data={"pair": sym, "price_usd": p.price_usd, "change_1h_pct": h1, "chain": p.chain},
                ))
        return alerts

    # ── Whale Moves ───────────────────────────────────────────────────────

    def _whale_moves(self, whales: list[WhaleTransaction]) -> list[Alert]:
        alerts = []
        for tx in whales:
            if tx.amount_usd < settings.whale_threshold_usd:
                continue
            label = tx.wallet_label or tx.wallet_address[:10] + "…"
            emoji = {"buy": "🟢", "sell": "🔴", "transfer": "🔵", "bridge": "🌉"}.get(tx.action, "⚪")
            alerts.append(Alert(
                alert_id=f"whale:{tx.tx_hash or tx.wallet_address}:{datetime.utcnow().strftime('%Y%m%d%H')}",
                alert_type="whale_move",
                severity="critical" if tx.amount_usd >= 1_000_000 else "warning",
                title=f"{emoji} Whale {tx.action.upper()}: ${tx.amount_usd:,.0f} of {tx.token_symbol}",
                description=(
                    f"{label} {tx.action}d ${tx.amount_usd:,.0f} of {tx.token_symbol} on {tx.chain}."
                    + (f" Via {tx.protocol}." if tx.protocol else "")
                ),
                data={
                    "wallet": tx.wallet_address,
                    "label": tx.wallet_label,
                    "token": tx.token_symbol,
                    "amount_usd": tx.amount_usd,
                    "action": tx.action,
                    "chain": tx.chain,
                    "tx_hash": tx.tx_hash,
                },
            ))
        return alerts
