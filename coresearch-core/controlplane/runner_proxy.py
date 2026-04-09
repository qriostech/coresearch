"""HTTP proxy to runner instances.

Maintains a process-wide cache of httpx.Client instances keyed by runner_id and
exposes helpers for issuing calls to a chosen runner. Used by every router that
needs to delegate work to a runner.
"""
import httpx
from fastapi import HTTPException

from connections.postgres.connection import get_cursor
from shared.logging import request_id_var

from . import log

# runner_id -> client / url. Module-private state — never imported elsewhere.
_runner_clients: dict[int, httpx.Client] = {}
_runner_urls: dict[int, str] = {}


def get_runner_client(runner_id: int) -> httpx.Client:
    if runner_id in _runner_clients:
        return _runner_clients[runner_id]
    # Look up URL from DB
    with get_cursor() as cur:
        cur.execute("SELECT url, status FROM runners WHERE id = %s", (runner_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Runner {runner_id} not found")
    if row["status"] == "offline":
        raise HTTPException(503, f"Runner {runner_id} is offline")
    client = httpx.Client(base_url=row["url"], timeout=120)
    _runner_clients[runner_id] = client
    _runner_urls[runner_id] = row["url"]
    return client


def get_runner_url(runner_id: int) -> str:
    if runner_id in _runner_urls:
        return _runner_urls[runner_id]
    get_runner_client(runner_id)
    return _runner_urls[runner_id]


def runner_call(runner_id: int, method: str, path: str, **kwargs):
    rid = request_id_var.get()
    headers = kwargs.pop("headers", {})
    if rid:
        headers["x-request-id"] = rid
    kwargs["headers"] = headers

    client = get_runner_client(runner_id)
    log.debug("runner call", runner_id=runner_id, runner_method=method, runner_path=path)
    resp = client.request(method, path, **kwargs)
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            pass
        log.error("runner call failed", runner_id=runner_id, runner_path=path, status=resp.status_code, detail=detail)
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp


def any_active_runner_id() -> int | None:
    """Get any active runner for lightweight operations like git ls-remote."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM runners WHERE status = 'active' ORDER BY last_heartbeat DESC NULLS LAST LIMIT 1")
        row = cur.fetchone()
    return row["id"] if row else None


def get_runner_id_for_branch(branch_id: int) -> int:
    with get_cursor() as cur:
        cur.execute("SELECT runner_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    if row["runner_id"]:
        return row["runner_id"]
    # Fallback for branches created before multi-runner migration
    fallback = any_active_runner_id()
    if not fallback:
        raise HTTPException(503, "No runner available")
    return fallback
