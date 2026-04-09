"""Branch resource: CRUD, fork, session lifecycle, push, workdir editor, git ops.

Also exports a few helpers (``branch_columns``, ``build_branch_response``,
``branch_path_and_runner``, ``delete_branch_tree``) that other routers reuse —
``runners.py`` for the per-runner branch listing, and ``seeds.py`` for the
delete-seed cascade.
"""
import uuid as uuid_mod

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import (
    Branch,
    CreateBranchRequest,
    ForkBranchRequest,
    PushResponse,
    SessionAliveResponse,
    UpdateBranchRequest,
    WriteFileRequest,
)

from controlplane.runner_proxy import (
    any_active_runner_id,
    get_runner_id_for_branch,
    runner_call,
)

router = APIRouter(tags=["branches"])


# ---------------------------------------------------------------------------
# Helpers (also used by routers/runners.py and routers/seeds.py)
# ---------------------------------------------------------------------------

def branch_columns():
    return """b.id, b.uuid, b.seed_id, b.runner_id, b.name, b.description, b.path, b.sync_command,
              b.commit, b.git_branch, b.created_at, b.parent_branch_id, b.parent_iteration_hash"""


def build_branch_response(branch_row, session_row=None):
    result = dict(branch_row)
    if session_row:
        result["session"] = dict(session_row)
    else:
        result["session"] = None
    return result


def branch_path_and_runner(branch_id: int) -> tuple[str, int]:
    """Look up branch path and runner_id in one query."""
    with get_cursor() as cur:
        cur.execute("SELECT path, runner_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    runner_id = row["runner_id"]
    if not runner_id:
        runner_id = any_active_runner_id()
        if not runner_id:
            raise HTTPException(503, "No runner available")
    return row["path"], runner_id


def delete_branch_tree(branch_id: int):
    """Soft-delete a branch and all descendants. Runner calls first, then atomic DB update."""
    # Phase 1: Read
    with get_cursor() as cur:
        cur.execute("SELECT id, path, runner_id, seed_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        root = cur.fetchone()
        if not root:
            return

        runner_id = root["runner_id"]
        seed_id = root["seed_id"]
        to_visit = [root]
        all_branches = [root]
        visited = {root["id"]}

        while to_visit:
            current = to_visit.pop(0)
            cur.execute(
                "SELECT id, path, runner_id, seed_id FROM branches WHERE parent_branch_id = %s AND NOT deleted",
                (current["id"],),
            )
            for child in cur.fetchall():
                if child["id"] not in visited:
                    visited.add(child["id"])
                    all_branches.append(child)
                    to_visit.append(child)

        all_ids = [b["id"] for b in all_branches]

        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = ANY(%s)", (all_ids,))
        attach_commands = [s["attach_command"] for s in cur.fetchall()]

    # Phase 2: Runner calls — all branches share the same runner (inherited)
    if runner_id:
        for attach in attach_commands:
            try:
                runner_call(runner_id, "POST", "/sessions/kill", params={"attach_command": attach})
            except Exception:
                pass

        for b in all_branches:
            try:
                runner_call(b["runner_id"] or runner_id, "POST", "/soft-delete", json={"path": b["path"]})
            except Exception:
                pass

    # Phase 3: DB writes in one transaction
    with get_cursor(autocommit=False) as cur:
        cur.execute("UPDATE sessions SET status = 'killed', ended_at = now() WHERE branch_id = ANY(%s)", (all_ids,))
        cur.execute("UPDATE branches SET deleted = TRUE WHERE id = ANY(%s)", (all_ids,))

    for bid in all_ids:
        event_bus.emit("branch.deleted", seed_id=seed_id, branch_id=bid)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/seeds/{seed_id}/branches", response_model=list[Branch])
def get_branches(seed_id: int):
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {branch_columns()},
                       s.id AS s_id, s.branch_id AS s_branch_id, s.runner, s.attach_command, s.agent,
                       s.status, s.started_at, s.ended_at, s.created_at AS s_created_at
                FROM branches b
                LEFT JOIN sessions s ON s.branch_id = b.id
                WHERE b.seed_id = %s AND NOT b.deleted
                ORDER BY b.created_at DESC""",
            (seed_id,),
        )
        results = []
        for row in cur.fetchall():
            branch_data = {
                "id": row["id"], "uuid": row["uuid"], "seed_id": row["seed_id"],
                "runner_id": row["runner_id"],
                "name": row["name"], "description": row["description"], "path": row["path"],
                "sync_command": row["sync_command"], "commit": row["commit"],
                "git_branch": row["git_branch"], "created_at": row["created_at"],
                "parent_branch_id": row["parent_branch_id"],
                "parent_iteration_hash": row["parent_iteration_hash"],
            }
            session_data = None
            if row["s_id"] is not None:
                session_data = {
                    "id": row["s_id"], "branch_id": row["s_branch_id"],
                    "runner": row["runner"], "attach_command": row["attach_command"],
                    "agent": row["agent"], "status": row["status"],
                    "started_at": row["started_at"], "ended_at": row["ended_at"],
                    "created_at": row["s_created_at"],
                }
            results.append(build_branch_response(branch_data, session_data))
        return results


@router.post("/seeds/{seed_id}/branches", response_model=Branch, status_code=201)
def post_branch(seed_id: int, body: CreateBranchRequest):
    with get_cursor() as cur:
        cur.execute("SELECT repository_url, branch, commit, access_token FROM seeds WHERE id = %s AND NOT deleted", (seed_id,))
        seed = cur.fetchone()
        if not seed:
            raise HTTPException(404, "Seed not found")

    # Runner must be specified
    runner_id = body.runner_id
    if not runner_id:
        runner_id = any_active_runner_id()
    if not runner_id:
        raise HTTPException(400, "No runner available")

    # Lazy-resolve empty commit (e.g. default bootstrap seed from storage_definition.sql).
    # Persist the resolved branch/commit so subsequent branches from this seed share the same start state.
    source_branch = seed["branch"]
    source_commit = seed["commit"]
    if not source_commit:
        resolved = runner_call(runner_id, "POST", "/resolve-ref", json={
            "repository_url": seed["repository_url"],
            "branch": source_branch or None,
            "commit": None,
            "access_token": seed.get("access_token"),
        }).json()
        source_branch = resolved["branch"]
        source_commit = resolved["commit"]
        with get_cursor() as cur:
            cur.execute(
                "UPDATE seeds SET branch = %s, commit = %s WHERE id = %s",
                (source_branch, source_commit, seed_id),
            )

    branch_uuid = str(uuid_mod.uuid4())

    # Runner handles clone, checkout, tmux session
    resp = runner_call(runner_id, "POST", "/init-branch", json={
        "name": body.name,
        "uuid": branch_uuid,
        "repository_url": seed["repository_url"],
        "source_branch": source_branch,
        "source_commit": source_commit,
        "access_token": seed.get("access_token"),
    })
    result = resp.json()

    with get_cursor(autocommit=False) as cur:
        cur.execute(
            """INSERT INTO branches (uuid, seed_id, runner_id, name, description, path, sync_command, commit, git_branch)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, seed_id, runner_id, name, description, path, sync_command, commit, git_branch,
                         created_at, parent_branch_id, parent_iteration_hash""",
            (branch_uuid, seed_id, runner_id, body.name, body.description, result["path"],
             result["sync_command"], result["commit"], result["git_branch"]),
        )
        branch_row = cur.fetchone()

        cur.execute(
            """INSERT INTO sessions (branch_id, runner, attach_command, agent, status, started_at)
               VALUES (%s, %s, %s, %s, 'active', now())
               RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at""",
            (branch_row["id"], body.runner, result["attach_command"], body.agent),
        )
        session_row = cur.fetchone()

    event_bus.emit("branch.created", seed_id=seed_id, branch_id=branch_row["id"])
    return build_branch_response(branch_row, session_row)


@router.patch("/branches/{branch_id}", status_code=204)
def update_branch(branch_id: int, body: UpdateBranchRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE branches SET description = %s WHERE id = %s AND NOT deleted RETURNING id",
            (body.description, branch_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Branch not found")


@router.post("/branches/{branch_id}/fork", response_model=Branch, status_code=201)
def fork_branch_endpoint(branch_id: int, req: ForkBranchRequest):
    with get_cursor() as cur:
        cur.execute("SELECT seed_id, path, runner_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        source = cur.fetchone()
        if not source:
            raise HTTPException(404, "Branch not found")

        cur.execute("SELECT repository_url FROM seeds WHERE id = %s", (source["seed_id"],))
        seed = cur.fetchone()
        if not seed:
            raise HTTPException(404, "Seed not found")

    # Inherit runner from parent branch
    runner_id = source["runner_id"]
    branch_uuid = str(uuid_mod.uuid4())

    resp = runner_call(runner_id, "POST", "/init-branch", json={
        "name": req.name,
        "uuid": branch_uuid,
        "repository_url": seed["repository_url"],
        "source_branch": "",
        "source_commit": req.iteration_hash,
        "source_branch_path": source["path"],
    })
    result = resp.json()

    with get_cursor(autocommit=False) as cur:
        cur.execute(
            """INSERT INTO branches (uuid, seed_id, runner_id, name, description, path, sync_command, commit, git_branch, parent_branch_id, parent_iteration_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, seed_id, runner_id, name, description, path, sync_command, commit, git_branch,
                         created_at, parent_branch_id, parent_iteration_hash""",
            (branch_uuid, source["seed_id"], runner_id, req.name, req.description, result["path"],
             result["sync_command"], result["commit"], result["git_branch"], branch_id, req.iteration_hash),
        )
        branch_row = cur.fetchone()

        cur.execute(
            """INSERT INTO sessions (branch_id, runner, attach_command, agent, status, started_at)
               VALUES (%s, 'tmux', %s, %s, 'active', now())
               RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at""",
            (branch_row["id"], result["attach_command"], req.agent),
        )
        session_row = cur.fetchone()

    event_bus.emit("branch.created", seed_id=source["seed_id"], branch_id=branch_row["id"])
    return build_branch_response(branch_row, session_row)


@router.delete("/branches/{branch_id}", status_code=204)
def delete_branch_endpoint(branch_id: int):
    delete_branch_tree(branch_id)


# --- Session lifecycle (delegate to runner) ---

@router.get("/branches/{branch_id}/session-alive", response_model=SessionAliveResponse)
def get_session_alive(branch_id: int):
    runner_id = get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if not row:
        return {"alive": False}
    resp = runner_call(runner_id, "GET", "/sessions/alive", params={"attach_command": row["attach_command"]})
    return resp.json()


@router.post("/branches/{branch_id}/renew", response_model=Branch)
def renew_branch(branch_id: int):
    runner_id = get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {branch_columns()}
                FROM branches b WHERE b.id = %s AND NOT b.deleted""",
            (branch_id,),
        )
        branch_row = cur.fetchone()
        if not branch_row:
            raise HTTPException(404, "Branch not found")
        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        old = cur.fetchone()

    old_attach = old["attach_command"] if old and old["attach_command"] else None

    renew_params = {"working_dir": branch_row["path"]}
    if old_attach:
        renew_params["old_attach_command"] = old_attach
    resp = runner_call(runner_id, "POST", "/sessions/renew", params=renew_params)
    new_attach = resp.json()["attach_command"]

    with get_cursor() as cur:
        cur.execute(
            """UPDATE sessions SET attach_command = %s, status = 'active', started_at = now(), ended_at = NULL
               WHERE branch_id = %s
               RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at""",
            (new_attach, branch_id),
        )
        session_row = cur.fetchone()

    event_bus.emit("session.status", branch_id=branch_id, status="active")
    return build_branch_response(branch_row, session_row)


@router.post("/branches/{branch_id}/kill", status_code=204)
def kill_branch(branch_id: int):
    runner_id = get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute("SELECT id, attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    runner_call(runner_id, "POST", "/sessions/kill", params={"attach_command": row["attach_command"]})
    with get_cursor() as cur:
        cur.execute("UPDATE sessions SET status = 'killed', ended_at = now() WHERE id = %s", (row["id"],))
    event_bus.emit("session.status", branch_id=branch_id, status="killed")


# --- Push ---

@router.post("/branches/{branch_id}/push", response_model=PushResponse)
def push_branch(branch_id: int, commit: str | None = Query(None)):
    runner_id = get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.path, b.git_branch, s.repository_url, s.access_token
               FROM branches b JOIN seeds s ON s.id = b.seed_id
               WHERE b.id = %s AND NOT b.deleted""",
            (branch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    if not row["git_branch"]:
        raise HTTPException(400, "Branch has no git_branch set")
    refspec = f"{commit}:refs/heads/{row['git_branch']}" if commit else row["git_branch"]
    resp = runner_call(runner_id, "POST", "/git/push", json={
        "repo_path": row["path"],
        "url": row["repository_url"],
        "refspec": refspec,
        "access_token": row.get("access_token"),
    })
    return resp.json()


# --- Workdir editor (proxy to runner) ---

@router.get("/branches/{branch_id}/workdir")
def get_workdir_tree(branch_id: int):
    path, runner_id = branch_path_and_runner(branch_id)
    resp = runner_call(runner_id, "GET", "/workdir/files", params={"root": path})
    return resp.json()


@router.get("/branches/{branch_id}/workdir/file")
def get_workdir_file(branch_id: int, path: str = Query(...)):
    branch_path, runner_id = branch_path_and_runner(branch_id)
    resp = runner_call(runner_id, "GET", "/workdir/file", params={"root": branch_path, "path": path})
    return PlainTextResponse(resp.text)


@router.put("/branches/{branch_id}/workdir/file", status_code=204)
def put_workdir_file(branch_id: int, body: WriteFileRequest):
    path, runner_id = branch_path_and_runner(branch_id)
    runner_call(runner_id, "PUT", "/workdir/file", json={"root": path, "path": body.path, "content": body.content})


@router.post("/branches/{branch_id}/workdir/commit", status_code=204)
def commit_workdir(branch_id: int):
    path, runner_id = branch_path_and_runner(branch_id)
    runner_call(runner_id, "POST", "/workdir/commit", params={"root": path})


# --- Git ops (proxy to runner) ---

@router.get("/branches/{branch_id}/diff")
def get_diff(branch_id: int, from_hash: str = Query(...), to_hash: str = Query(...)):
    path, runner_id = branch_path_and_runner(branch_id)
    resp = runner_call(runner_id, "GET", "/git/diff", params={"repo_path": path, "from_hash": from_hash, "to_hash": to_hash})
    return PlainTextResponse(resp.text)


@router.get("/branches/{branch_id}/tree")
def get_tree(branch_id: int, hash: str = Query(...)):
    path, runner_id = branch_path_and_runner(branch_id)
    resp = runner_call(runner_id, "GET", "/git/tree", params={"repo_path": path, "hash": hash})
    return resp.json()


@router.get("/branches/{branch_id}/file")
def get_file(branch_id: int, hash: str = Query(...), path: str = Query(...)):
    branch_path, runner_id = branch_path_and_runner(branch_id)
    resp = runner_call(runner_id, "GET", "/git/file", params={"repo_path": branch_path, "hash": hash, "path": path})
    return PlainTextResponse(resp.text)
