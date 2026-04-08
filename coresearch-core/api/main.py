import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from connections.postgres.connection import get_cursor
from core.project import create_project, list_projects
from core.seed import create_seed, list_seeds, delete_seed
from core.branch import create_branch, list_branches, renew_branch_session, kill_branch_session, is_session_alive, fork_branch, delete_branch
from core import daemon
from schemas.project import Project
from schemas.seed import Seed
from schemas.branch import Branch
from schemas.session import Session
from schemas.iteration import Iteration, IterationMetric, IterationVisual, IterationComment

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
        # Ensure default project exists
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
        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sessions')")
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
            # Drop old columns from branches
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS runner")
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS attach_command")
            cur.execute("ALTER TABLE branches DROP COLUMN IF EXISTS agent")
            # Drop old branch_history trigger and table (replaced by session_history)
            cur.execute("DROP TRIGGER IF EXISTS branch_audit ON branches")
            cur.execute("DROP FUNCTION IF EXISTS log_branch_change()")
            cur.execute("DROP TABLE IF EXISTS branch_history")

@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    asyncio.create_task(daemon.run())
    yield


app = FastAPI(title="Coresearch", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# --- Projects ---

@app.get("/projects", response_model=list[Project])
def get_projects():
    return list_projects()


@app.post("/projects", response_model=Project, status_code=201)
def post_project(body: CreateProjectRequest):
    return create_project(body.name, body.user_id, body.llm_provider, body.llm_model)


# --- Seeds ---

@app.get("/projects/{project_id}/seeds", response_model=list[Seed])
def get_seeds(project_id: int):
    return list_seeds(project_id)


@app.post("/projects/{project_id}/seeds", response_model=Seed, status_code=201)
def post_seed(project_id: int, body: CreateSeedRequest):
    try:
        return create_seed(project_id, body.name, body.repository_url, body.branch, body.commit, body.access_token)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/seeds/{seed_id}", status_code=204)
def delete_seed_endpoint(seed_id: int):
    try:
        delete_seed(seed_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Branches ---

@app.get("/seeds/{seed_id}/branches", response_model=list[Branch])
def get_branches(seed_id: int):
    return list_branches(seed_id)


@app.post("/seeds/{seed_id}/branches", response_model=Branch, status_code=201)
def post_branch(seed_id: int, body: CreateBranchRequest):
    try:
        return create_branch(seed_id, body.name, body.runner, body.agent, body.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/branches/{branch_id}/session-alive")
def get_session_alive(branch_id: int):
    return {"alive": is_session_alive(branch_id)}


@app.post("/branches/{branch_id}/kill", status_code=204)
def kill_branch(branch_id: int):
    try:
        kill_branch_session(branch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/branches/{branch_id}/renew", response_model=Branch)
def renew_branch(branch_id: int):
    try:
        return renew_branch_session(branch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/branches/{branch_id}", status_code=204)
def delete_branch_endpoint(branch_id: int):
    try:
        delete_branch(branch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class UpdateBranchRequest(BaseModel):
    description: str


@app.patch("/branches/{branch_id}", status_code=204)
def update_branch(branch_id: int, body: UpdateBranchRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE branches SET description = %s WHERE id = %s AND NOT deleted RETURNING id",
            (body.description, branch_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")


class ForkBranchRequest(BaseModel):
    name: str
    description: str = ""
    iteration_hash: str
    agent: str = "default"


@app.post("/branches/{branch_id}/fork", response_model=Branch)
def fork_branch_endpoint(branch_id: int, req: ForkBranchRequest):
    try:
        return fork_branch(branch_id, req.name, req.iteration_hash, agent=req.agent, description=req.description)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/branches/{branch_id}/push")
def push_branch(branch_id: int, commit: str | None = Query(None)):
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.path, b.git_branch, s.repository_url, s.access_token
               FROM branches b JOIN seeds s ON s.id = b.seed_id
               WHERE b.id = %s AND NOT b.deleted""",
            (branch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    git_branch = row["git_branch"]
    if not git_branch:
        raise HTTPException(status_code=400, detail="Branch has no git_branch set")
    # Build authenticated remote URL from seed
    url = row["repository_url"]
    token = row["access_token"] or os.environ.get("GITHUB_TOKEN")
    if token and "://" in url:
        scheme, rest = url.split("://", 1)
        url = f"{scheme}://oauth2:{token}@{rest}"
    refspec = f"{commit}:refs/heads/{git_branch}" if commit else git_branch
    try:
        result = subprocess.run(
            ["git", "-C", row["path"], "push", url, refspec],
            capture_output=True, text=True, check=True, timeout=60,
        )
        return {"message": result.stdout.strip() or "pushed successfully"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=e.stderr.strip() or str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="push timed out")


class SeedFromIterationRequest(BaseModel):
    name: str
    branch_id: int
    iteration_hash: str


@app.post("/projects/{project_id}/seeds/from-iteration", response_model=Seed, status_code=201)
def seed_from_iteration(project_id: int, body: SeedFromIterationRequest):
    """Push iteration to remote, then create a seed pointing at that commit."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.path, b.git_branch, b.seed_id, s.repository_url, s.access_token
               FROM branches b JOIN seeds s ON s.id = b.seed_id
               WHERE b.id = %s AND NOT b.deleted""",
            (body.branch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")

    git_branch = row["git_branch"]
    if not git_branch:
        raise HTTPException(status_code=400, detail="Branch has no git_branch — it was created before this feature was added. Create a new branch to use this.")
    repo_url = row["repository_url"]
    access_token = row["access_token"]
    token = access_token or os.environ.get("GITHUB_TOKEN")

    # Build push URL
    push_url = repo_url
    if token and "://" in repo_url:
        scheme, rest = repo_url.split("://", 1)
        push_url = f"{scheme}://oauth2:{token}@{rest}"

    # Push up to this iteration (skip if already on remote)
    refspec = f"{body.iteration_hash}:refs/heads/{git_branch}"
    try:
        subprocess.run(
            ["git", "-C", row["path"], "push", push_url, refspec],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except subprocess.CalledProcessError:
        pass  # commit is already reachable on the remote

    # Create seed pointing at the pushed state
    try:
        return create_seed(project_id, body.name, repo_url,
                           branch=git_branch, commit=body.iteration_hash,
                           access_token=access_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Working tree editor ---

@app.get("/branches/{branch_id}/workdir")
def get_workdir_tree(branch_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    root = row["path"]
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            files.append(os.path.relpath(full, root))
    return sorted(files)


@app.get("/branches/{branch_id}/workdir/file")
def get_workdir_file(branch_id: int, path: str = Query(...)):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    full = os.path.realpath(os.path.join(row["path"], path))
    if not full.startswith(os.path.realpath(row["path"])):
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        return PlainTextResponse(open(full).read())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class WriteFileRequest(BaseModel):
    path: str
    content: str


@app.put("/branches/{branch_id}/workdir/file", status_code=204)
def put_workdir_file(branch_id: int, body: WriteFileRequest):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    full = os.path.realpath(os.path.join(row["path"], body.path))
    if not full.startswith(os.path.realpath(row["path"])):
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").write(body.content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/branches/{branch_id}/workdir/commit", status_code=204)
def commit_workdir(branch_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    path = row["path"]
    try:
        subprocess.run(["git", "-C", path, "add", "-A"], check=True, timeout=10)
        result = subprocess.run(
            ["git", "-C", path, "diff", "--cached", "--quiet"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "-C", path,
                 "-c", "user.name=coresearch",
                 "-c", "user.email=coresearch@local",
                 "commit", "-m", "branching edit"],
                check=True, timeout=10,
            )
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Iterations ---

@app.get("/branches/{branch_id}/iterations", response_model=list[Iteration])
def get_iterations(branch_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, branch_id, hash, name, description, created_at FROM iterations WHERE branch_id = %s ORDER BY created_at",
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
            result.append(Iteration(**row, metrics=metrics, visuals=visuals, comments=comments))
    return result


class UpdateIterationRequest(BaseModel):
    description: str | None = None


@app.patch("/iterations/{iteration_id}")
def update_iteration(iteration_id: int, body: UpdateIterationRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE iterations SET description = %s WHERE id = %s RETURNING id",
            (body.description, iteration_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Iteration not found")


class AddCommentRequest(BaseModel):
    body: str
    user_id: int = 1


@app.post("/iterations/{iteration_id}/comments", status_code=201)
def add_comment(iteration_id: int, req: AddCommentRequest):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO iteration_comments (iteration_id, user_id, body)
               VALUES (%s, %s, %s)
               RETURNING id""",
            (iteration_id, req.user_id, req.body),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Iteration not found")
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
            "SELECT path FROM iteration_visuals WHERE iteration_id = %s AND filename = %s",
            (iteration_id, filename),
        )
        row = cur.fetchone()
    if not row or not os.path.isfile(row["path"]):
        raise HTTPException(status_code=404, detail="Visual not found")
    return FileResponse(row["path"])


# --- Diff ---

@app.get("/branches/{branch_id}/diff")
def get_diff(branch_id: int, from_hash: str = Query(...), to_hash: str = Query(...)):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    try:
        result = subprocess.run(
            ["git", "diff", from_hash, to_hash],
            cwd=row["path"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Diff timed out")
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip())
    return PlainTextResponse(result.stdout)


# --- File browser ---

@app.get("/branches/{branch_id}/tree")
def get_tree(branch_id: int, hash: str = Query(...)):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", hash],
            cwd=row["path"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timed out")
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip())
    files = [f for f in result.stdout.strip().split("\n") if f]
    return files


@app.get("/branches/{branch_id}/file")
def get_file(branch_id: int, hash: str = Query(...), path: str = Query(...)):
    with get_cursor() as cur:
        cur.execute("SELECT path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    try:
        result = subprocess.run(
            ["git", "show", f"{hash}:{path}"],
            cwd=row["path"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Timed out")
    if result.returncode != 0:
        raise HTTPException(400, result.stderr.strip())
    return PlainTextResponse(result.stdout)


# --- Terminal ---

def _set_pty_size(fd: int, rows: int, cols: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@app.websocket("/ws/branch/{branch_id}")
async def terminal_ws(websocket: WebSocket, branch_id: int):
    await websocket.accept()

    def _lookup_branch():
        with get_cursor() as cur:
            cur.execute(
                """SELECT s.attach_command FROM sessions s
                   JOIN branches b ON b.id = s.branch_id
                   WHERE s.branch_id = %s AND NOT b.deleted""",
                (branch_id,),
            )
            return cur.fetchone()

    row = await asyncio.to_thread(_lookup_branch)

    if not row:
        await websocket.close(code=1008)
        return

    cmd = row["attach_command"].split()
    master_fd, slave_fd = pty.openpty()

    # Wait for the client to send its real terminal size before spawning tmux
    try:
        msg = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        payload = json.loads(msg)
        if payload.get("type") == "resize":
            _set_pty_size(master_fd, payload["rows"], payload["cols"])
        else:
            _set_pty_size(master_fd, 24, 80)
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        return

    proc = subprocess.Popen(
        cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True, preexec_fn=os.setsid,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    os.close(slave_fd)

    loop = asyncio.get_event_loop()
    write_fd = os.dup(master_fd)

    # Read side: asyncio stream for efficient output buffering
    pty_reader = asyncio.StreamReader()
    read_transport, _ = await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(pty_reader),
        os.fdopen(master_fd, "rb", 0),
    )

    async def send_output():
        try:
            while True:
                data = await pty_reader.read(65536)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    async def receive_input():
        while True:
            try:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    await loop.run_in_executor(None, os.write, write_fd, msg["bytes"])
                elif msg.get("text"):
                    payload = json.loads(msg["text"])
                    if payload["type"] == "resize":
                        _set_pty_size(write_fd, payload["rows"], payload["cols"])
            except WebSocketDisconnect:
                break
            except OSError:
                break
            except Exception:
                continue

    try:
        await asyncio.gather(send_output(), receive_input())
    finally:
        read_transport.close()
        proc.terminate()
        try:
            os.close(write_fd)
        except OSError:
            pass
