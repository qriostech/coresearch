"""Background tasks launched from the FastAPI lifespan."""
import asyncio

from connections.postgres.connection import get_cursor
from shared.events import event_bus

from controlplane import log
from controlplane.runner_proxy import evict_runner


async def stale_runner_check():
    """Periodically check for runners that missed heartbeats and mark them offline."""
    while True:
        await asyncio.sleep(60)
        try:
            with get_cursor() as cur:
                # Runners that missed 3 heartbeats (90s)
                cur.execute("""
                    UPDATE runners SET status = 'offline'
                    WHERE status = 'active'
                      AND last_heartbeat < now() - interval '90 seconds'
                    RETURNING id, name
                """)
                stale = cur.fetchall()
                for r in stale:
                    log.warn("runner went offline", runner_id=r["id"], runner_name=r["name"])
                    # Drop the cached httpx client so subsequent calls return 503
                    # instead of timing out against an unreachable host.
                    evict_runner(r["id"])
                    event_bus.emit("runner.offline", runner_id=r["id"], runner_name=r["name"])
                    # Mark all active sessions on this runner as dead
                    cur.execute("""
                        UPDATE sessions SET status = 'dead', ended_at = now()
                        WHERE status = 'active'
                          AND branch_id IN (SELECT id FROM branches WHERE runner_id = %s)
                        RETURNING branch_id
                    """, (r["id"],))
                    for s in cur.fetchall():
                        event_bus.emit("session.status", branch_id=s["branch_id"], status="dead")
        except Exception as e:
            log.error("stale runner check failed", error=str(e))
