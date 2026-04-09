"""Internal API consumed by the runner daemon, plus the deep /health endpoint.

These endpoints are not user-facing — they exist so that runners can register,
heartbeat, report iterations/metrics/visuals/docs, and update session statuses.
The deep /health endpoint also lives here because it inspects every registered
runner.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import (
    InternalDocRequest,
    InternalIterationRequest,
    InternalMetricsRequest,
    InternalSessionStatusRequest,
    InternalVisualRequest,
    RegisterRunnerRequest,
)

from .. import log
from ..runner_proxy import get_runner_client

router = APIRouter()


@router.get("/internal/health")
def internal_health():
    return {"status": "ok"}


# --- Runner registration ---

@router.post("/internal/runners/register")
def register_runner(body: RegisterRunnerRequest):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO runners (name, url, status, capabilities, last_heartbeat)
               VALUES (%s, %s, 'active', %s, now())
               ON CONFLICT (name) DO UPDATE
               SET url = EXCLUDED.url, status = 'active', capabilities = EXCLUDED.capabilities, last_heartbeat = now()
               RETURNING id, name, url, status""",
            (body.name, body.url, json.dumps(body.capabilities)),
        )
        row = cur.fetchone()
    log.info("runner registered", runner_id=row["id"], runner_name=row["name"], runner_url=row["url"])
    event_bus.emit("runner.registered", runner_id=row["id"], runner_name=row["name"])
    return dict(row)


@router.post("/internal/runners/{runner_id}/heartbeat", status_code=204)
def runner_heartbeat(runner_id: int):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE runners SET last_heartbeat = now(), status = 'active' WHERE id = %s RETURNING id",
            (runner_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Runner not found")


@router.get("/internal/runners")
def list_runners():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status, capabilities, registered_at, last_heartbeat FROM runners ORDER BY id")
        return cur.fetchall()


# --- Deep health check (user-facing) ---

@router.get("/health")
def health_check():
    checks: dict = {"postgres": "ok"}
    healthy = True

    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as e:
        checks["postgres"] = str(e)
        healthy = False

    # Check all registered runners
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status FROM runners")
        runners = cur.fetchall()

    for r in runners:
        key = f"runner:{r['name']}"
        if r["status"] == "offline":
            checks[key] = "offline"
            healthy = False
            continue
        try:
            client = get_runner_client(r["id"])
            resp = client.get("/health", timeout=5)
            checks[key] = "ok" if resp.status_code == 200 else f"status {resp.status_code}"
            if resp.status_code != 200:
                healthy = False
        except Exception as e:
            checks[key] = str(e)
            healthy = False

    if not runners:
        checks["runners"] = "none registered"

    return JSONResponse({"status": "healthy" if healthy else "unhealthy", "checks": checks}, status_code=200 if healthy else 503)


# --- Branches / sessions snapshot for runner daemon ---

@router.get("/internal/branches")
def internal_list_branches():
    with get_cursor() as cur:
        cur.execute("SELECT id, path FROM branches WHERE NOT deleted")
        return cur.fetchall()


@router.get("/internal/sessions/active")
def internal_active_sessions():
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, branch_id, attach_command FROM sessions WHERE status = 'active'"
        )
        return cur.fetchall()


# --- Iteration ingest from runner daemon ---

@router.post("/internal/iterations", status_code=201)
def internal_create_iteration(body: InternalIterationRequest):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO iterations (branch_id, hash, name)
               VALUES (%s, %s, %s)
               ON CONFLICT (branch_id, hash) DO NOTHING
               RETURNING id""",
            (body.branch_id, body.hash, body.hash),
        )
        row = cur.fetchone()
        if row:
            event_bus.emit("iteration.created", branch_id=body.branch_id, hash=body.hash)
            return {"id": row["id"]}
        cur.execute(
            "SELECT id FROM iterations WHERE branch_id = %s AND hash = %s",
            (body.branch_id, body.hash),
        )
        return {"id": cur.fetchone()["id"]}


@router.post("/internal/iterations/metrics", status_code=204)
def internal_upsert_metrics(body: InternalMetricsRequest):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM iterations WHERE branch_id = %s AND hash = %s",
            (body.branch_id, body.hash),
        )
        row = cur.fetchone()
        if not row:
            return
        iteration_id = row["id"]
        for key, value in body.metrics.items():
            cur.execute(
                """INSERT INTO iteration_metrics (iteration_id, key, value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (iteration_id, key)
                   DO UPDATE SET value = EXCLUDED.value, recorded_at = now()""",
                (iteration_id, key, value),
            )
    event_bus.emit("iteration.metrics", branch_id=body.branch_id, hash=body.hash)


@router.post("/internal/iterations/visuals", status_code=204)
def internal_upsert_visual(body: InternalVisualRequest):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM iterations WHERE branch_id = %s AND hash = %s",
            (body.branch_id, body.hash),
        )
        row = cur.fetchone()
        if not row:
            return
        cur.execute(
            """INSERT INTO iteration_visuals (iteration_id, filename, format, path)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (iteration_id, filename) DO NOTHING""",
            (row["id"], body.filename, body.format, body.path),
        )
    event_bus.emit("iteration.visuals", branch_id=body.branch_id, hash=body.hash)


@router.post("/internal/iterations/doc", status_code=204)
def internal_upsert_doc(body: InternalDocRequest):
    allowed = {"hypothesis", "analysis", "guidelines_version"}
    if body.field not in allowed:
        return
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE iterations SET {body.field} = %s WHERE branch_id = %s AND hash = %s",
            (body.content, body.branch_id, body.hash),
        )
    event_bus.emit("iteration.doc", branch_id=body.branch_id, hash=body.hash, field=body.field)


@router.patch("/internal/sessions/{session_id}/status", status_code=204)
def internal_update_session_status(session_id: int, body: InternalSessionStatusRequest):
    with get_cursor() as cur:
        if body.status in ("dead", "killed"):
            cur.execute(
                "UPDATE sessions SET status = %s, ended_at = now() WHERE id = %s RETURNING branch_id",
                (body.status, session_id),
            )
        else:
            cur.execute(
                "UPDATE sessions SET status = %s WHERE id = %s RETURNING branch_id",
                (body.status, session_id),
            )
        row = cur.fetchone()
    if row:
        event_bus.emit("session.status", branch_id=row["branch_id"], status=body.status)
