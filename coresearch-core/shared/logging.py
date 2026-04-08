import json
import sys
import threading
import time
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone

# Context var for request ID — set by middleware, read by logger
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Ring buffer for log streaming to frontend
_log_buffer_lock = threading.Lock()
_log_subscribers: dict[str, list] = {}  # service_name -> list of asyncio.Queue


class StructuredLogger:
    def __init__(self, service: str, buffer_size: int = 1000):
        self.service = service
        self._buffer: deque[dict] = deque(maxlen=buffer_size)

    def _emit(self, level: str, message: str, **kwargs):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "service": self.service,
            "message": message,
        }
        rid = request_id_var.get()
        if rid:
            entry["request_id"] = rid
        entry.update(kwargs)

        # Write to stderr as JSON
        line = json.dumps(entry, default=str)
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

        # Store in ring buffer
        with _log_buffer_lock:
            self._buffer.append(entry)

        # Notify subscribers
        self._notify(entry)

    def _notify(self, entry: dict):
        with _log_buffer_lock:
            subscribers = _log_subscribers.get(self.service, [])
            dead = []
            for q in subscribers:
                try:
                    q.put_nowait(entry)
                except Exception:
                    dead.append(q)
            for q in dead:
                subscribers.remove(q)

    def info(self, message: str, **kwargs):
        self._emit("info", message, **kwargs)

    def warn(self, message: str, **kwargs):
        self._emit("warn", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._emit("error", message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._emit("debug", message, **kwargs)

    def get_recent(self, n: int = 100) -> list[dict]:
        with _log_buffer_lock:
            return list(self._buffer)[-n:]

    def subscribe(self, queue):
        with _log_buffer_lock:
            subs = _log_subscribers.setdefault(self.service, [])
            subs.append(queue)

    def unsubscribe(self, queue):
        with _log_buffer_lock:
            subs = _log_subscribers.get(self.service, [])
            if queue in subs:
                subs.remove(queue)
