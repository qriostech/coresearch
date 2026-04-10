"""Cory session resource: list, create, kill, delete.

A cory session is a tmux session that lives inside the cory container, owned
directly by a user (no seed/branch). The controlplane manages the lifecycle
the same way it manages branch sessions on the runner: it calls the cory
container's HTTP API and mirrors the result into the cory_sessions table.
"""
import uuid as uuid_mod

from fastapi import APIRouter, HTTPException

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import CorySession, CreateCorySessionRequest

from controlplane import log
from controlplane.cory_proxy import cory_call

router = APIRouter(tags=["cory_sessions"])


CORY_SESSION_COLUMNS = """id, uuid, user_id, name, kind, attach_command, agent,
                          status, started_at, ended_at, created_at"""


def row_to_cory_session(row: dict) -> CorySession:
    return CorySession(**{k: row[k] for k in (
        "id", "uuid", "user_id", "name", "kind", "attach_command",
        "agent", "status", "started_at", "ended_at", "created_at",
    )})


@router.get("/cory-sessions", response_model=list[CorySession])
def list_cory_sessions(user_id: int | None = None):
    with get_cursor() as cur:
        if user_id is None:
            cur.execute(
                f"SELECT {CORY_SESSION_COLUMNS} FROM cory_sessions "
                "WHERE NOT deleted ORDER BY created_at DESC"
            )
        else:
            cur.execute(
                f"SELECT {CORY_SESSION_COLUMNS} FROM cory_sessions "
                "WHERE user_id = %s AND NOT deleted ORDER BY created_at DESC",
                (user_id,),
            )
        return [row_to_cory_session(row) for row in cur.fetchall()]


@router.post("/cory-sessions", response_model=CorySession, status_code=201)
def create_cory_session(body: CreateCorySessionRequest):
    # Ask the cory container to spawn the tmux session before we touch the DB
    # — if cory is unreachable we want to fail without leaving an orphaned row.
    resp = cory_call("POST", "/sessions", json={"working_dir": "/home/coresearch"})
    attach_command = resp.json()["attach_command"]

    session_uuid = str(uuid_mod.uuid4())
    name = body.name or f"cory-{session_uuid[:8]}"

    with get_cursor() as cur:
        cur.execute(
            f"""INSERT INTO cory_sessions
                (uuid, user_id, name, kind, attach_command, agent, status, started_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'active', now())
                RETURNING {CORY_SESSION_COLUMNS}""",
            (session_uuid, body.user_id, name, body.kind, attach_command, body.agent),
        )
        row = cur.fetchone()

    log.info("cory session created", id=row["id"], name=name)
    event_bus.emit("cory_session.created", cory_session_id=row["id"])
    return row_to_cory_session(row)


@router.post("/cory-sessions/{cory_session_id}/kill", status_code=204)
def kill_cory_session(cory_session_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, attach_command, status FROM cory_sessions WHERE id = %s AND NOT deleted",
            (cory_session_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Cory session not found")

    if row["attach_command"]:
        cory_call("POST", "/sessions/kill", params={"attach_command": row["attach_command"]})

    with get_cursor() as cur:
        cur.execute(
            "UPDATE cory_sessions SET status = 'killed', ended_at = now() WHERE id = %s",
            (cory_session_id,),
        )

    log.info("cory session killed", id=cory_session_id)
    event_bus.emit("cory_session.status", cory_session_id=cory_session_id, status="killed")


@router.delete("/cory-sessions/{cory_session_id}", status_code=204)
def delete_cory_session(cory_session_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, attach_command, status FROM cory_sessions WHERE id = %s AND NOT deleted",
            (cory_session_id,),
        )
        row = cur.fetchone()
    if not row:
        return  # idempotent

    # Kill the tmux session if still alive — best-effort, swallow errors so the
    # DB row is always cleaned up even if the cory container is down.
    if row["attach_command"] and row["status"] == "active":
        try:
            cory_call("POST", "/sessions/kill", params={"attach_command": row["attach_command"]})
        except Exception as e:
            log.warn("cory session delete: kill failed", id=cory_session_id, error=str(e))

    with get_cursor() as cur:
        cur.execute(
            "UPDATE cory_sessions SET deleted = TRUE, status = 'killed', ended_at = COALESCE(ended_at, now()) WHERE id = %s",
            (cory_session_id,),
        )

    log.info("cory session deleted", id=cory_session_id)
    event_bus.emit("cory_session.deleted", cory_session_id=cory_session_id)
