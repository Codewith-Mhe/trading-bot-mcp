"""
events/event_bus.py
====================
Typed async Event Bus for agent-to-agent communication.
No agent calls another agent directly — they emit events and listen for events.

Core Events Role 3 owns:
  TRADE_REQUEST       → Safety Agent listens, runs parallel safety scan
  SAFETY_RESULT       → Safety Agent emits after scan completes
  ALPHA_FOUND         → Research Agent emits when smart money activity detected
  COPY_TRADE_REQUEST  → Copy Trade Agent emits when watched wallet moves

Usage:
    from events.event_bus import bus, Event

    # Listen (decorator style)
    @bus.on(Event.TRADE_REQUEST)
    async def handle(payload: dict):
        ...

    # Emit
    await bus.emit(Event.SAFETY_RESULT, report.model_dump())
"""

from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from enum import Enum

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class Event(str, Enum):
    # Inbound to Role 3
    TRADE_REQUEST      = "TRADE_REQUEST"
    TRADE_EXECUTED     = "TRADE_EXECUTED"

    # Outbound from Role 3
    SAFETY_RESULT      = "SAFETY_RESULT"
    ALPHA_FOUND        = "ALPHA_FOUND"
    COPY_TRADE_REQUEST = "COPY_TRADE_REQUEST"

    # Cross-role (shared typing)
    QUOTE_RESULT       = "QUOTE_RESULT"
    EXECUTE_TRADE      = "EXECUTE_TRADE"
    EXECUTE_SELL       = "EXECUTE_SELL"
    REJECT_TRADE       = "REJECT_TRADE"
    POSITION_UPDATE    = "POSITION_UPDATE"


class EventBus:
    """
    Async event bus. All handlers for an event run concurrently.
    One handler failing does not affect others.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Handler]] = defaultdict(list)
        self._log: list[dict] = []

    def on(self, event: Event) -> Callable:
        """Decorator — register an async handler."""
        def decorator(fn: Handler) -> Handler:
            self._listeners[event.value].append(fn)
            logger.debug("Registered: %s → %s", event.value, fn.__name__)
            return fn
        return decorator

    def register(self, event: Event, handler: Handler) -> None:
        """Programmatic registration."""
        self._listeners[event.value].append(handler)

    async def emit(self, event: Event, payload: dict = {}) -> None:
        """Emit event — all handlers run concurrently via asyncio.gather."""
        handlers = self._listeners.get(event.value, [])
        self._log.append({"event": event.value, "keys": list(payload.keys())})
        if len(self._log) > 500:
            self._log = self._log[-500:]

        if not handlers:
            logger.debug("No listeners for: %s", event.value)
            return

        logger.info("📡 %s → %d handler(s)", event.value, len(handlers))

        await asyncio.gather(
            *[self._call(h, payload) for h in handlers],
            return_exceptions=True,
        )

    async def _call(self, handler: Handler, payload: dict) -> None:
        try:
            await handler(payload)
        except Exception as exc:
            logger.error("Handler %s error: %s", handler.__name__, exc)
            raise

    def listeners(self, event: Event) -> list[str]:
        return [h.__name__ for h in self._listeners.get(event.value, [])]

    def recent_events(self, n: int = 20) -> list[dict]:
        return self._log[-n:]


# Shared singleton
bus = EventBus()
