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


async def _register(client: httpx.AsyncClient) -> int:
    """POST /internal/runners/register, retrying forever with exponential
    backoff (2s → 30s cap). Returns the runner_id assigned by the controlplane.

    Called at startup and again from the heartbeat loop when the controlplane
    has forgotten our row (404 on heartbeat — typically after a controlplane
    restart with a wiped DB).
    """
    runner_url = os.environ.get("RUNNER_URL", f"http://{RUNNER_NAME}:{RUNNER_PORT}")
    backoff = 2.0
    while True:
        try:
            resp = await client.post("/internal/runners/register", json={
                "name": RUNNER_NAME,
                "url": runner_url,
            })
            # raise_for_status so HTTP 4xx/5xx surfaces as an exception and
            # triggers retry instead of crashing later on data["id"].
            resp.raise_for_status()
            data = resp.json()
            runner_id = data["id"]
            log.info("registered with controlplane", runner_id=runner_id, runner_name=RUNNER_NAME)
            return runner_id
        except Exception as e:
            log.warn("registration failed, will retry", error=str(e), retry_in_s=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _register_and_heartbeat(controlplane_url: str):
    """Register with controlplane, then send heartbeats every 30s.

    Both the initial registration and the periodic heartbeat are resilient:

    - Registration retries forever with exponential backoff. The runner has no
      purpose if it can't register, so silently giving up isn't a useful
      failure mode. Both the cold-start case (controlplane not yet up →
      connection refused) and the controlplane-rejects case (HTTP 5xx,
      malformed response) flow through the same retry path.

    - Each heartbeat uses raise_for_status() so HTTP errors actually surface
      as exceptions instead of silently passing through. On a 404 — meaning
      the controlplane has lost our runner row, typically after a controlplane
      restart with a wiped DB — re-register and continue with whatever id the
      controlplane assigns (the same one if the row was just temporarily
      gone, a new one if the DB was wiped). Other failures (network errors,
      5xx) just log and retry next interval.
    """
    global _runner_id
    client = httpx.AsyncClient(base_url=controlplane_url, timeout=10)

    _runner_id = await _register(client)

    while True:
        await asyncio.sleep(30)
        try:
            resp = await client.post(f"/internal/runners/{_runner_id}/heartbeat")
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.warn(
                    "heartbeat returned 404, controlplane has lost our row — re-registering",
                    runner_id=_runner_id,
                )
                _runner_id = await _register(client)
            else:
                log.warn("heartbeat failed", status=e.response.status_code, error=str(e))
        except Exception as e:
            log.warn("heartbeat failed", error=str(e))


def start_heartbeat(controlplane_url: str):
    global _heartbeat_task
    _heartbeat_task = asyncio.create_task(_register_and_heartbeat(controlplane_url))


def stop_heartbeat():
    if _heartbeat_task:
        _heartbeat_task.cancel()
