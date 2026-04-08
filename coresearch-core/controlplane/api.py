import json
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from connections.postgres.connection import get_cursor
from shared.logging import StructuredLogger, request_id_var
from shared.middleware import RequestLoggingMiddleware
from shared.events import event_bus

log = StructuredLogger("controlplane")

# Runner HTTP client cache: runner_id -> httpx.Client
_runner_clients: dict[int, httpx.Client] = {}
_runner_urls: dict[int, str] = {}


def _get_runner_client(runner_id: int) -> httpx.Client:
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


def _get_runner_url(runner_id: int) -> str:
    if runner_id in _runner_urls:
        return _runner_urls[runner_id]
    _get_runner_client(runner_id)
    return _runner_urls[runner_id]


def _runner_call(runner_id: int, method: str, path: str, **kwargs):
    rid = request_id_var.get()
    headers = kwargs.pop("headers", {})
    if rid:
        headers["x-request-id"] = rid
    kwargs["headers"] = headers

    client = _get_runner_client(runner_id)
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


def _any_active_runner_id() -> int | None:
    """Get any active runner for lightweight operations like git ls-remote."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM runners WHERE status = 'active' ORDER BY last_heartbeat DESC NULLS LAST LIMIT 1")
        row = cur.fetchone()
    return row["id"] if row else None


def _get_runner_id_for_branch(branch_id: int) -> int:
    with get_cursor() as cur:
        cur.execute("SELECT runner_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    if row["runner_id"]:
        return row["runner_id"]
    # Fallback for branches created before multi-runner migration
    fallback = _any_active_runner_id()
    if not fallback:
        raise HTTPException(503, "No runner available")
    return fallback


# --- Migrations ---

def run_migrations():
    with get_cursor() as cur:
        # Legacy: rename old sessions -> projects (skip if projects already exists)
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'projects') AS exists")
        projects_exists = cur.fetchone()["exists"]
        if not projects_exists:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.columns
                    WHERE table_name = 'sessions' AND column_name = 'session_root'
                ) AS exists
            """)
            if cur.fetchone()["exists"]:
                cur.execute("ALTER TABLE sessions RENAME TO projects")
                cur.execute("ALTER TABLE projects RENAME COLUMN session_root TO project_root")
                cur.execute("ALTER TABLE seeds RENAME COLUMN session_id TO project_id")
        cur.execute("ALTER TABLE seeds ADD COLUMN IF NOT EXISTS branch TEXT NOT NULL DEFAULT 'main'")
        cur.execute("ALTER TABLE seeds ADD COLUMN IF NOT EXISTS commit TEXT NOT NULL DEFAULT ''")
        cur.execute("ALTER TABLE seeds ADD COLUMN IF NOT EXISTS access_token TEXT")
        cur.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS git_branch TEXT NOT NULL DEFAULT ''")
        cur.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
        cur.execute("ALTER TABLE branches ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE seeds ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("SELECT id FROM projects LIMIT 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO projects (name, uuid, user_id, project_root) VALUES ('default', 'default', 1, '/data/sessions/default')")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS iteration_comments (
                id           SERIAL PRIMARY KEY,
                iteration_id INT NOT NULL REFERENCES iterations(id),
                user_id      INT NOT NULL REFERENCES users(id) DEFAULT 1,
                body         TEXT NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        # Create sessions table and migrate data from branches
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sessions') AS exists")
        if not cur.fetchone()["exists"]:
            cur.execute("""
                CREATE TABLE sessions (
                    id             SERIAL PRIMARY KEY,
                    branch_id      INT NOT NULL UNIQUE REFERENCES branches(id),
                    runner         TEXT NOT NULL DEFAULT 'tmux',
                    attach_command TEXT NOT NULL DEFAULT '',
                    agent          TEXT NOT NULL DEFAULT '',
                    status         TEXT NOT NULL DEFAULT 'inactive',
                    started_at     TIMESTAMPTZ,
                    ended_at       TIMESTAMPTZ,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE session_history (
                    id             SERIAL PRIMARY KEY,
                    session_id     INT NOT NULL REFERENCES sessions(id),
                    runner         TEXT NOT NULL,
                    attach_command TEXT NOT NULL,
                    agent          TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    change_type    TEXT NOT NULL,
                    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION log_session_change() RETURNS TRIGGER AS $$
                BEGIN
                    INSERT INTO session_history (session_id, attach_command, runner, agent, status, change_type)
                    VALUES (NEW.id, NEW.attach_command, NEW.runner, NEW.agent, NEW.status,
                            CASE WHEN TG_OP = 'INSERT' THEN 'created' ELSE 'updated' END);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            cur.execute("""
                CREATE TRIGGER session_audit
                AFTER INSERT OR UPDATE ON sessions
                FOR EACH ROW EXECUTE FUNCTION log_session_change()
            """)
            # Migrate existing branch session data (only non-deleted branches)
            cur.execute("""
                SELECT id, runner, attach_command, agent, deleted FROM branches
                WHERE EXISTS (SELECT 1 FROM information_schema.columns
                              WHERE table_name = 'branches' AND column_name = 'runner')
            """)
            for row in cur.fetchall():
                status = 'inactive' if row["deleted"] else 'active'
                cur.execute(
                    """INSERT INTO sessions (branch_id, runner, attach_command, agent, status, started_at)
                       VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'active' THEN now() ELSE NULL END)
                       ON CONFLICT (branch_id) DO NOTHING""",
                    (row["id"], row["runner"], row["attach_command"], row["agent"], status, status),
                )
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS runner")
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS attach_command")
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS agent")
            cur.execute("DROP TRIGGER IF EXISTS branch_audit ON branches")
            cur.execute("DROP FUNCTION IF EXISTS log_branch_change()")
            cur.execute("DROP TABLE IF EXISTS branch_history")

        # --- Runners migration ---
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'runners') AS exists")
        if not cur.fetchone()["exists"]:
            log.info("creating runners tables")
            cur.execute("""
                CREATE TABLE runners (
                    id             SERIAL PRIMARY KEY,
                    name           TEXT NOT NULL UNIQUE,
                    url            TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'active',
                    capabilities   JSONB NOT NULL DEFAULT '{}',
                    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_heartbeat TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE runner_history (
                    id          SERIAL PRIMARY KEY,
                    runner_id   INT NOT NULL REFERENCES runners(id),
                    status      TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE OR REPLACE FUNCTION log_runner_change() RETURNS TRIGGER AS $$
                BEGIN
                    INSERT INTO runner_history (runner_id, status, change_type)
                    VALUES (NEW.id, NEW.status,
                            CASE WHEN TG_OP = 'INSERT' THEN 'registered' ELSE 'updated' END);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            cur.execute("""
                CREATE TRIGGER runner_audit
                AFTER INSERT OR UPDATE ON runners
                FOR EACH ROW EXECUTE FUNCTION log_runner_change()
            """)

        # Add runner_id to branches (nullable initially for migration)
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name = 'branches' AND column_name = 'runner_id'
            ) AS exists
        """)
        if not cur.fetchone()["exists"]:
            log.info("adding runner_id to branches")
            cur.execute("ALTER TABLE branches ADD COLUMN runner_id INT REFERENCES runners(id)")

        # Drop path from seeds (access_token is kept for branch cloning)
        cur.execute("ALTER TABLE seeds DROP COLUMN IF EXISTS path")
        cur.execute("ALTER TABLE seeds ADD COLUMN IF NOT EXISTS access_token TEXT")

        # Add iteration doc columns
        cur.execute("ALTER TABLE iterations ADD COLUMN IF NOT EXISTS hypothesis TEXT")
        cur.execute("ALTER TABLE iterations ADD COLUMN IF NOT EXISTS analysis TEXT")
        cur.execute("ALTER TABLE iterations ADD COLUMN IF NOT EXISTS guidelines_version TEXT")


async def _stale_runner_check():
    """Periodically check for runners that missed heartbeats and mark them offline."""
    import asyncio
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    log.info("starting controlplane")
    run_migrations()
    log.info("migrations complete")
    stale_task = asyncio.create_task(_stale_runner_check())
    yield
    stale_task.cancel()
    log.info("shutting down controlplane")


app = FastAPI(title="Coresearch Control Plane", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware, logger=log, generate_request_id=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# User-facing API
# ============================================================

# --- Request bodies ---

class CreateProjectRequest(BaseModel):
    name: str
    user_id: int = 1
    llm_provider: str = "default_llm"
    llm_model: str = "default_model"


class CreateSeedRequest(BaseModel):
    name: str
    repository_url: str
    branch: str | None = None
    commit: str | None = None
    access_token: str | None = None


class CreateBranchRequest(BaseModel):
    name: str
    description: str = ""
    runner: str = "tmux"
    agent: str = "default"
    runner_id: int | None = None


class UpdateBranchRequest(BaseModel):
    description: str


class ForkBranchRequest(BaseModel):
    name: str
    description: str = ""
    iteration_hash: str
    agent: str = "default"


class SeedFromIterationRequest(BaseModel):
    name: str
    branch_id: int
    iteration_hash: str


class WriteFileRequest(BaseModel):
    path: str
    content: str


class AddCommentRequest(BaseModel):
    body: str
    user_id: int = 1


class UpdateIterationRequest(BaseModel):
    description: str | None = None


# --- Runners (user-facing) ---

@app.get("/runners")
def get_runners():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status, capabilities, registered_at, last_heartbeat FROM runners ORDER BY id")
        return cur.fetchall()


@app.get("/runners/{runner_id}/branches")
def get_runner_branches(runner_id: int):
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {_branch_columns()},
                       s.id AS s_id, s.branch_id AS s_branch_id, s.runner, s.attach_command, s.agent,
                       s.status, s.started_at, s.ended_at, s.created_at AS s_created_at
                FROM branches b
                LEFT JOIN sessions s ON s.branch_id = b.id
                WHERE b.runner_id = %s AND NOT b.deleted
                ORDER BY b.created_at DESC""",
            (runner_id,),
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
            results.append(_build_branch_response(branch_data, session_data))
        return results


class RenameRunnerRequest(BaseModel):
    name: str


@app.patch("/runners/{runner_id}", status_code=204)
def rename_runner(runner_id: int, body: RenameRunnerRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE runners SET name = %s WHERE id = %s RETURNING id",
            (body.name, runner_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Runner not found")
    event_bus.emit("runner.registered", runner_id=runner_id, runner_name=body.name)


# --- Projects ---

@app.get("/projects")
def get_projects():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root FROM projects ORDER BY created_at DESC")
        return cur.fetchall()


@app.post("/projects", status_code=201)
def post_project(body: CreateProjectRequest):
    import uuid
    project_uuid = str(uuid.uuid4())
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO projects (name, uuid, user_id, llm_provider, llm_model, project_root)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root""",
            (body.name, project_uuid, body.user_id, body.llm_provider, body.llm_model, f"project_{project_uuid}"),
        )
        return cur.fetchone()


# --- Seeds ---

@app.get("/projects/{project_id}/seeds")
def get_seeds(project_id: int):
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, uuid, project_id, name, repository_url, branch, commit, created_at
               FROM seeds WHERE project_id = %s AND NOT deleted ORDER BY created_at DESC""",
            (project_id,),
        )
        return cur.fetchall()


@app.post("/projects/{project_id}/seeds", status_code=201)
def post_seed(project_id: int, body: CreateSeedRequest):
    import uuid
    with get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Project not found")

    seed_uuid = str(uuid.uuid4())

    # Resolve branch/commit via any active runner (just a git ls-remote)
    runner_id = _any_active_runner_id()
    if runner_id:
        resp = _runner_call(runner_id, "POST", "/resolve-ref", json={
            "repository_url": body.repository_url,
            "branch": body.branch,
            "commit": body.commit,
            "access_token": body.access_token,
        })
        result = resp.json()
        resolved_branch = result["branch"]
        resolved_commit = result["commit"]
    else:
        # No runners available — use provided values or defaults
        resolved_branch = body.branch or "main"
        resolved_commit = body.commit or ""

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO seeds (uuid, project_id, name, repository_url, branch, commit, access_token)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, project_id, name, repository_url, branch, commit, created_at""",
            (seed_uuid, project_id, body.name, body.repository_url, resolved_branch, resolved_commit, body.access_token or None),
        )
        row = cur.fetchone()

    event_bus.emit("seed.created", project_id=project_id, seed_id=row["id"])
    return row


@app.delete("/seeds/{seed_id}", status_code=204)
def delete_seed_endpoint(seed_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT id FROM seeds WHERE id = %s AND NOT deleted", (seed_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Seed not found")
        cur.execute("SELECT id FROM branches WHERE seed_id = %s AND NOT deleted", (seed_id,))
        branch_ids = [row["id"] for row in cur.fetchall()]

    # Delete all branches (each handles its own runner calls)
    for bid in branch_ids:
        _delete_branch_tree(bid)

    with get_cursor() as cur:
        cur.execute("UPDATE seeds SET deleted = TRUE WHERE id = %s", (seed_id,))

    event_bus.emit("seed.deleted", seed_id=seed_id)


# --- Branches ---

def _branch_columns():
    return """b.id, b.uuid, b.seed_id, b.runner_id, b.name, b.description, b.path, b.sync_command,
              b.commit, b.git_branch, b.created_at, b.parent_branch_id, b.parent_iteration_hash"""


def _build_branch_response(branch_row, session_row=None):
    result = dict(branch_row)
    if session_row:
        result["session"] = dict(session_row)
    else:
        result["session"] = None
    return result


@app.get("/seeds/{seed_id}/branches")
def get_branches(seed_id: int):
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {_branch_columns()},
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
            results.append(_build_branch_response(branch_data, session_data))
        return results


@app.post("/seeds/{seed_id}/branches", status_code=201)
def post_branch(seed_id: int, body: CreateBranchRequest):
    import uuid as uuid_mod
    with get_cursor() as cur:
        cur.execute("SELECT repository_url, branch, commit, access_token FROM seeds WHERE id = %s AND NOT deleted", (seed_id,))
        seed = cur.fetchone()
        if not seed:
            raise HTTPException(404, "Seed not found")

    # Runner must be specified
    runner_id = body.runner_id
    if not runner_id:
        runner_id = _any_active_runner_id()
    if not runner_id:
        raise HTTPException(400, "No runner available")

    branch_uuid = str(uuid_mod.uuid4())

    # Runner handles clone, checkout, tmux session
    resp = _runner_call(runner_id, "POST", "/init-branch", json={
        "name": body.name,
        "uuid": branch_uuid,
        "repository_url": seed["repository_url"],
        "source_branch": seed["branch"],
        "source_commit": seed["commit"],
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
    return _build_branch_response(branch_row, session_row)


@app.patch("/branches/{branch_id}", status_code=204)
def update_branch(branch_id: int, body: UpdateBranchRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE branches SET description = %s WHERE id = %s AND NOT deleted RETURNING id",
            (body.description, branch_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Branch not found")


@app.post("/branches/{branch_id}/fork", status_code=201)
def fork_branch_endpoint(branch_id: int, req: ForkBranchRequest):
    import uuid as uuid_mod
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

    resp = _runner_call(runner_id, "POST", "/init-branch", json={
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
    return _build_branch_response(branch_row, session_row)


def _delete_branch_tree(branch_id: int):
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
                _runner_call(runner_id, "POST", "/sessions/kill", params={"attach_command": attach})
            except Exception:
                pass

        for b in all_branches:
            try:
                _runner_call(b["runner_id"] or runner_id, "POST", "/soft-delete", json={"path": b["path"]})
            except Exception:
                pass

    # Phase 3: DB writes in one transaction
    with get_cursor(autocommit=False) as cur:
        cur.execute("UPDATE sessions SET status = 'killed', ended_at = now() WHERE branch_id = ANY(%s)", (all_ids,))
        cur.execute("UPDATE branches SET deleted = TRUE WHERE id = ANY(%s)", (all_ids,))

    for bid in all_ids:
        event_bus.emit("branch.deleted", seed_id=seed_id, branch_id=bid)


@app.delete("/branches/{branch_id}", status_code=204)
def delete_branch_endpoint(branch_id: int):
    _delete_branch_tree(branch_id)


# --- Session endpoints (delegate to runner) ---

@app.get("/branches/{branch_id}/session-alive")
def get_session_alive(branch_id: int):
    runner_id = _get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if not row:
        return {"alive": False}
    resp = _runner_call(runner_id, "GET", "/sessions/alive", params={"attach_command": row["attach_command"]})
    return resp.json()


@app.post("/branches/{branch_id}/renew")
def renew_branch(branch_id: int):
    runner_id = _get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {_branch_columns()}
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
    resp = _runner_call(runner_id, "POST", "/sessions/renew", params=renew_params)
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
    return _build_branch_response(branch_row, session_row)


@app.post("/branches/{branch_id}/kill", status_code=204)
def kill_branch(branch_id: int):
    runner_id = _get_runner_id_for_branch(branch_id)
    with get_cursor() as cur:
        cur.execute("SELECT id, attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Session not found")
    _runner_call(runner_id, "POST", "/sessions/kill", params={"attach_command": row["attach_command"]})
    with get_cursor() as cur:
        cur.execute("UPDATE sessions SET status = 'killed', ended_at = now() WHERE id = %s", (row["id"],))
    event_bus.emit("session.status", branch_id=branch_id, status="killed")


# --- Push ---

@app.post("/branches/{branch_id}/push")
def push_branch(branch_id: int, commit: str | None = Query(None)):
    runner_id = _get_runner_id_for_branch(branch_id)
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
    resp = _runner_call(runner_id, "POST", "/git/push", json={
        "repo_path": row["path"],
        "url": row["repository_url"],
        "refspec": refspec,
        "access_token": row.get("access_token"),
    })
    return resp.json()


@app.post("/projects/{project_id}/seeds/from-iteration", status_code=201)
def seed_from_iteration(project_id: int, body: SeedFromIterationRequest):
    import uuid as uuid_mod
    runner_id = _get_runner_id_for_branch(body.branch_id)
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.path, b.git_branch, b.seed_id, s.repository_url, s.access_token
               FROM branches b JOIN seeds s ON s.id = b.seed_id
               WHERE b.id = %s AND NOT b.deleted""",
            (body.branch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    if not row["git_branch"]:
        raise HTTPException(400, "Branch has no git_branch set")

    refspec = f"{body.iteration_hash}:refs/heads/{row['git_branch']}"
    try:
        _runner_call(runner_id, "POST", "/git/push", json={
            "repo_path": row["path"],
            "url": row["repository_url"],
            "refspec": refspec,
            "access_token": row.get("access_token"),
        })
    except HTTPException:
        pass  # already on remote

    with get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Project not found")

    seed_uuid = str(uuid_mod.uuid4())

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO seeds (uuid, project_id, name, repository_url, branch, commit)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, project_id, name, repository_url, branch, commit, created_at""",
            (seed_uuid, project_id, body.name, row["repository_url"],
             row["git_branch"], body.iteration_hash),
        )
        return cur.fetchone()


# --- Workdir (proxy to runner) ---

def _branch_path_and_runner(branch_id: int) -> tuple[str, int]:
    """Look up branch path and runner_id in one query."""
    with get_cursor() as cur:
        cur.execute("SELECT path, runner_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    runner_id = row["runner_id"]
    if not runner_id:
        runner_id = _any_active_runner_id()
        if not runner_id:
            raise HTTPException(503, "No runner available")
    return row["path"], runner_id


@app.get("/branches/{branch_id}/workdir")
def get_workdir_tree(branch_id: int):
    path, runner_id = _branch_path_and_runner(branch_id)
    resp = _runner_call(runner_id, "GET", "/workdir/files", params={"root": path})
    return resp.json()


@app.get("/branches/{branch_id}/workdir/file")
def get_workdir_file(branch_id: int, path: str = Query(...)):
    branch_path, runner_id = _branch_path_and_runner(branch_id)
    resp = _runner_call(runner_id, "GET", "/workdir/file", params={"root": branch_path, "path": path})
    return PlainTextResponse(resp.text)


@app.put("/branches/{branch_id}/workdir/file", status_code=204)
def put_workdir_file(branch_id: int, body: WriteFileRequest):
    path, runner_id = _branch_path_and_runner(branch_id)
    _runner_call(runner_id, "PUT", "/workdir/file", json={"root": path, "path": body.path, "content": body.content})


@app.post("/branches/{branch_id}/workdir/commit", status_code=204)
def commit_workdir(branch_id: int):
    path, runner_id = _branch_path_and_runner(branch_id)
    _runner_call(runner_id, "POST", "/workdir/commit", params={"root": path})


# --- Git ops (proxy to runner) ---

@app.get("/branches/{branch_id}/diff")
def get_diff(branch_id: int, from_hash: str = Query(...), to_hash: str = Query(...)):
    path, runner_id = _branch_path_and_runner(branch_id)
    resp = _runner_call(runner_id, "GET", "/git/diff", params={"repo_path": path, "from_hash": from_hash, "to_hash": to_hash})
    return PlainTextResponse(resp.text)


@app.get("/branches/{branch_id}/tree")
def get_tree(branch_id: int, hash: str = Query(...)):
    path, runner_id = _branch_path_and_runner(branch_id)
    resp = _runner_call(runner_id, "GET", "/git/tree", params={"repo_path": path, "hash": hash})
    return resp.json()


@app.get("/branches/{branch_id}/file")
def get_file(branch_id: int, hash: str = Query(...), path: str = Query(...)):
    branch_path, runner_id = _branch_path_and_runner(branch_id)
    resp = _runner_call(runner_id, "GET", "/git/file", params={"repo_path": branch_path, "hash": hash, "path": path})
    return PlainTextResponse(resp.text)


# --- Iterations ---

@app.get("/branches/{branch_id}/iterations")
def get_iterations(branch_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, branch_id, hash, name, description, hypothesis, analysis, guidelines_version, created_at FROM iterations WHERE branch_id = %s ORDER BY created_at",
            (branch_id,),
        )
        iterations = cur.fetchall()
        result = []
        for row in iterations:
            cur.execute(
                "SELECT id, iteration_id, key, value, recorded_at FROM iteration_metrics WHERE iteration_id = %s ORDER BY key",
                (row["id"],),
            )
            metrics = cur.fetchall()
            cur.execute(
                "SELECT id, iteration_id, filename, format, path, created_at FROM iteration_visuals WHERE iteration_id = %s ORDER BY filename",
                (row["id"],),
            )
            visuals = cur.fetchall()
            cur.execute(
                """SELECT c.id, c.iteration_id, c.user_id, u.name AS user_name, c.body, c.created_at
                   FROM iteration_comments c JOIN users u ON u.id = c.user_id
                   WHERE c.iteration_id = %s ORDER BY c.created_at""",
                (row["id"],),
            )
            comments = cur.fetchall()
            result.append({**dict(row), "metrics": [dict(m) for m in metrics], "visuals": [dict(v) for v in visuals], "comments": [dict(c) for c in comments]})
    return result


@app.patch("/iterations/{iteration_id}")
def update_iteration(iteration_id: int, body: UpdateIterationRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE iterations SET description = %s WHERE id = %s RETURNING id",
            (body.description, iteration_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Iteration not found")


@app.post("/iterations/{iteration_id}/comments", status_code=201)
def add_comment(iteration_id: int, req: AddCommentRequest):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO iteration_comments (iteration_id, user_id, body)
               VALUES (%s, %s, %s) RETURNING id""",
            (iteration_id, req.user_id, req.body),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Iteration not found")
    return {"id": row["id"]}


@app.delete("/iterations/{iteration_id}/comments/{comment_id}", status_code=204)
def delete_comment(iteration_id: int, comment_id: int):
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM iteration_comments WHERE id = %s AND iteration_id = %s",
            (comment_id, iteration_id),
        )


@app.get("/iterations/{iteration_id}/visuals/{filename}")
def get_visual(iteration_id: int, filename: str):
    with get_cursor() as cur:
        cur.execute(
            """SELECT v.path, i.branch_id
               FROM iteration_visuals v JOIN iterations i ON i.id = v.iteration_id
               WHERE v.iteration_id = %s AND v.filename = %s""",
            (iteration_id, filename),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Visual not found")
    runner_id = _get_runner_id_for_branch(row["branch_id"])
    resp = _runner_call(runner_id, "GET", "/visuals/file", params={"path": row["path"]})
    from fastapi.responses import Response
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "application/octet-stream"))


# --- Terminal WebSocket (proxy to runner) ---

@app.websocket("/ws/branch/{branch_id}")
async def terminal_ws(websocket: WebSocket, branch_id: int):
    import asyncio
    import websockets
    await websocket.accept()

    def _lookup():
        with get_cursor() as cur:
            cur.execute(
                """SELECT s.attach_command, b.runner_id FROM sessions s
                   JOIN branches b ON b.id = s.branch_id
                   WHERE s.branch_id = %s AND NOT b.deleted""",
                (branch_id,),
            )
            return cur.fetchone()

    row = await asyncio.to_thread(_lookup)
    if not row or not row["runner_id"]:
        await websocket.close(code=1008)
        return

    runner_url = _get_runner_url(row["runner_id"])
    runner_ws_url = runner_url.replace("http://", "ws://").replace("https://", "wss://")
    from urllib.parse import quote
    runner_uri = f"{runner_ws_url}/ws/terminal?attach_command={quote(row['attach_command'])}"

    try:
        async with websockets.connect(runner_uri) as runner_ws:
            async def client_to_runner():
                while True:
                    try:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if msg.get("bytes"):
                            await runner_ws.send(msg["bytes"])
                        elif msg.get("text"):
                            await runner_ws.send(msg["text"])
                    except Exception:
                        break

            async def runner_to_client():
                try:
                    async for msg in runner_ws:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_runner(), runner_to_client())
    except Exception:
        await websocket.close(code=1011)


# ============================================================
# Log streaming
# ============================================================

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    import asyncio
    await websocket.accept()
    queue = asyncio.Queue(maxsize=500)
    event_bus.subscribe(queue)

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except Exception:
        pass
    finally:
        event_bus.unsubscribe(queue)


@app.websocket("/ws/logs/controlplane")
async def controlplane_log_stream(websocket: WebSocket):
    import asyncio
    await websocket.accept()
    queue = asyncio.Queue(maxsize=500)
    log.subscribe(queue)

    for entry in log.get_recent(100):
        await websocket.send_json(entry)

    try:
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except Exception:
        pass
    finally:
        log.unsubscribe(queue)


@app.websocket("/ws/logs/runner")
async def runner_log_stream(websocket: WebSocket, name: str = Query(None)):
    import asyncio
    import websockets
    await websocket.accept()

    # Find runner URL — use named runner or first active
    def _find_runner_url():
        with get_cursor() as cur:
            if name:
                cur.execute("SELECT url FROM runners WHERE name = %s", (name,))
            else:
                cur.execute("SELECT url FROM runners WHERE status = 'active' ORDER BY id LIMIT 1")
            row = cur.fetchone()
            return row["url"] if row else None

    url = await asyncio.to_thread(_find_runner_url)
    if not url:
        await websocket.close(code=1008)
        return

    runner_ws_url = url.replace("http://", "ws://").replace("https://", "wss://")

    try:
        async with websockets.connect(f"{runner_ws_url}/ws/logs") as runner_ws:
            async def forward():
                try:
                    async for msg in runner_ws:
                        await websocket.send_text(msg)
                except Exception:
                    pass

            async def keepalive():
                while True:
                    try:
                        await websocket.receive()
                    except Exception:
                        break

            await asyncio.gather(forward(), keepalive())
    except Exception:
        await websocket.close(code=1011)


# ============================================================
# Internal API (called by runner daemon)
# ============================================================

@app.get("/internal/health")
def internal_health():
    return {"status": "ok"}


# --- Runner registration ---

class RegisterRunnerRequest(BaseModel):
    name: str
    url: str
    capabilities: dict = {}


@app.post("/internal/runners/register")
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


@app.post("/internal/runners/{runner_id}/heartbeat", status_code=204)
def runner_heartbeat(runner_id: int):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE runners SET last_heartbeat = now(), status = 'active' WHERE id = %s RETURNING id",
            (runner_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Runner not found")


@app.get("/internal/runners")
def list_runners():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status, capabilities, registered_at, last_heartbeat FROM runners ORDER BY id")
        return cur.fetchall()


@app.get("/health")
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
            client = _get_runner_client(r["id"])
            resp = client.get("/health", timeout=5)
            checks[key] = "ok" if resp.status_code == 200 else f"status {resp.status_code}"
            if resp.status_code != 200:
                healthy = False
        except Exception as e:
            checks[key] = str(e)
            healthy = False

    if not runners:
        checks["runners"] = "none registered"

    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "healthy" if healthy else "unhealthy", "checks": checks}, status_code=200 if healthy else 503)


@app.get("/internal/branches")
def internal_list_branches():
    with get_cursor() as cur:
        cur.execute("SELECT id, path FROM branches WHERE NOT deleted")
        return cur.fetchall()


@app.get("/internal/sessions/active")
def internal_active_sessions():
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, branch_id, attach_command FROM sessions WHERE status = 'active'"
        )
        return cur.fetchall()


class InternalIterationRequest(BaseModel):
    branch_id: int
    hash: str


@app.post("/internal/iterations", status_code=201)
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


class InternalMetricsRequest(BaseModel):
    branch_id: int
    hash: str
    metrics: dict[str, float]


@app.post("/internal/iterations/metrics", status_code=204)
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


class InternalVisualRequest(BaseModel):
    branch_id: int
    hash: str
    filename: str
    format: str
    path: str


@app.post("/internal/iterations/visuals", status_code=204)
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


class InternalDocRequest(BaseModel):
    branch_id: int
    hash: str
    field: str  # "hypothesis", "analysis", "guidelines_version"
    content: str


@app.post("/internal/iterations/doc", status_code=204)
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


class InternalSessionStatusRequest(BaseModel):
    status: str


@app.patch("/internal/sessions/{session_id}/status", status_code=204)
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
