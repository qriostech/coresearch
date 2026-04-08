import asyncio
import json
import threading
from datetime import datetime, timezone


class EventBus:
    """In-process event bus. Emit events from sync code, consume from async WebSocket handlers."""

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def emit(self, event_type: str, **payload):
        event = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **payload,
        }
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def subscribe(self, queue: asyncio.Queue):
        with self._lock:
            self._subscribers.append(queue)

    def unsubscribe(self, queue: asyncio.Queue):
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)


# Singleton — shared across the controlplane process
event_bus = EventBus()
