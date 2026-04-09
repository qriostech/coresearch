"""Background registration + heartbeat with the controlplane.

The runner registers itself once on startup and then pings the controlplane
every 30s so it remains marked ``active``. State is module-private; the
lifespan starts and stops the task via the helpers below.
"""
import asyncio
import os

import httpx

from runner import log
from runner.config import RUNNER_NAME, RUNNER_PORT

_heartbeat_task: asyncio.Task | None = None
_runner_id: int | None = None


async def _register_and_heartbeat(controlplane_url: str):
    """Register with controlplane, then send heartbeats every 30s."""
    global _runner_id
    client = httpx.AsyncClient(base_url=controlplane_url, timeout=10)

    # Wait for controlplane to be ready
    while True:
        try:
            resp = await client.get("/internal/health")
            if resp.status_code == 200:
                break
        except Exception:
            pass
        log.warn("waiting for controlplane to register")
        await asyncio.sleep(2)

    # Register
    runner_url = os.environ.get("RUNNER_URL", f"http://{RUNNER_NAME}:{RUNNER_PORT}")
    try:
        resp = await client.post("/internal/runners/register", json={
            "name": RUNNER_NAME,
            "url": runner_url,
        })
        data = resp.json()
        _runner_id = data["id"]
        log.info("registered with controlplane", runner_id=_runner_id, runner_name=RUNNER_NAME)
    except Exception as e:
        log.error("failed to register", error=str(e))
        await client.aclose()
        return

    # Heartbeat loop
    while True:
        await asyncio.sleep(30)
        try:
            await client.post(f"/internal/runners/{_runner_id}/heartbeat")
        except Exception as e:
            log.warn("heartbeat failed", error=str(e))


def start_heartbeat(controlplane_url: str):
    global _heartbeat_task
    _heartbeat_task = asyncio.create_task(_register_and_heartbeat(controlplane_url))


def stop_heartbeat():
    if _heartbeat_task:
        _heartbeat_task.cancel()
