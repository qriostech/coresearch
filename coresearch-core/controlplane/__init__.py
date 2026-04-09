"""Coresearch control plane package.

Exposes a single shared StructuredLogger instance so that the websocket log
streaming endpoint sees the full ring buffer regardless of which router emitted
the log entry. Routers and helpers should ``from controlplane import log``
rather than instantiating their own.
"""
from shared.logging import StructuredLogger

log = StructuredLogger("controlplane")
