import asyncio
import fcntl
import json
import os
import pty
import shutil
import struct
import subprocess
import termios
import uuid

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from runner.tmux import create_tmux_session, is_tmux_alive, kill_tmux_session
from runner.git_ops import (
    resolve_branch_and_commit, clone_repo, clone_local, checkout_branch,
    git_diff, git_tree, git_show_file, git_push,
)
from runner.daemon import Daemon
from shared.logging import StructuredLogger
from shared.middleware import RequestLoggingMiddleware

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/data/sessions")
RUNNER_NAME = os.environ.get("RUNNER_NAME", "runner-default")
RUNNER_PORT = int(os.environ.get("RUNNER_PORT", "8001"))

log = StructuredLogger("runner")
daemon = Daemon()

_heartbeat_task = None
_runner_id: int | None = None


async def _register_and_heartbeat(controlplane_url: str):
    """Register with controlplane, then send heartbeats every 30s."""
    global _runner_id
    import httpx

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_task
    log.info("starting runner", storage_root=STORAGE_ROOT, runner_name=RUNNER_NAME)
    controlplane_url = os.environ.get("CONTROLPLANE_URL", "http://controlplane:8000")
    daemon.start(controlplane_url)
    _heartbeat_task = asyncio.create_task(_register_and_heartbeat(controlplane_url))
    yield
    if _heartbeat_task:
        _heartbeat_task.cancel()
    daemon.stop()
    log.info("runner stopped")


app = FastAPI(title="Coresearch Runner", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware, logger=log, generate_request_id=False)


# --- Log streaming ---

@app.websocket("/ws/logs")
async def log_stream(websocket: WebSocket):
    await websocket.accept()
    import asyncio
    queue = asyncio.Queue(maxsize=500)
    log.subscribe(queue)

    # Send recent logs first
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


# --- Health ---

@app.get("/health")
def health_check():
    checks = {"tmux": "ok", "storage": "ok"}
    healthy = True

    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, timeout=5)
    if result.returncode not in (0, 1):  # 1 = no sessions, which is fine
        checks["tmux"] = "tmux not available"
        healthy = False

    if not os.path.isdir(STORAGE_ROOT):
        checks["storage"] = f"{STORAGE_ROOT} not found"
        healthy = False
    else:
        try:
            test_file = os.path.join(STORAGE_ROOT, ".health_check")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as e:
            checks["storage"] = f"not writable: {e}"
            healthy = False

    from fastapi.responses import JSONResponse
    return JSONResponse(
        {"status": "healthy" if healthy else "unhealthy", "checks": checks},
        status_code=200 if healthy else 503,
    )


# --- Ref resolution ---

class ResolveRefRequest(BaseModel):
    repository_url: str
    branch: str | None = None
    commit: str | None = None
    access_token: str | None = None


class ResolveRefResponse(BaseModel):
    branch: str
    commit: str


@app.post("/resolve-ref", response_model=ResolveRefResponse)
def resolve_ref(body: ResolveRefRequest):
    resolved_branch, resolved_commit = resolve_branch_and_commit(
        body.repository_url, body.branch, body.commit, body.access_token,
    )
    return ResolveRefResponse(branch=resolved_branch, commit=resolved_commit)


# --- Branch operations ---

class InitBranchRequest(BaseModel):
    name: str
    uuid: str
    repository_url: str
    source_branch: str
    source_commit: str
    access_token: str | None = None
    source_branch_path: str | None = None  # for forking from existing branch


class InitBranchResponse(BaseModel):
    path: str
    commit: str
    git_branch: str
    attach_command: str
    sync_command: str


@app.post("/init-branch", response_model=InitBranchResponse)
def init_branch(body: InitBranchRequest):
    # Runner decides where to put the branch
    branch_dir = os.path.join(STORAGE_ROOT, "branches", f"{body.name}_{body.uuid[:8]}")
    git_branch = f"coresearch/{body.name}-{body.uuid[:8]}"

    if body.source_branch_path:
        log.info("cloning from local branch", source=body.source_branch_path, dest=branch_dir)
        clone_local(body.source_branch_path, branch_dir)
    else:
        log.info("cloning from remote", repo=body.repository_url, dest=branch_dir)
        clone_repo(body.repository_url, branch_dir, body.source_branch, body.access_token)

    commit = checkout_branch(branch_dir, git_branch, body.source_commit)

    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=branch_dir)
    log.info("branch initialized", branch=body.name, git_branch=git_branch, commit=commit[:12], tmux_session=session_uuid)
    sync_command = f"rsync -av {branch_dir}/"

    return InitBranchResponse(
        path=branch_dir,
        commit=commit,
        git_branch=git_branch,
        attach_command=attach_command,
        sync_command=sync_command,
    )


# --- Soft delete ---

class SoftDeleteRequest(BaseModel):
    path: str


@app.post("/soft-delete", status_code=204)
def soft_delete(body: SoftDeleteRequest):
    if not os.path.isdir(body.path):
        return
    parent = os.path.dirname(body.path)
    fordeletion = os.path.join(parent, ".fordeletion")
    os.makedirs(fordeletion, exist_ok=True)
    dest = os.path.join(fordeletion, os.path.basename(body.path))
    shutil.move(body.path, dest)
    log.info("soft deleted", path=body.path)


# --- Session operations ---

class CreateSessionRequest(BaseModel):
    working_dir: str


class CreateSessionResponse(BaseModel):
    attach_command: str


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest):
    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=body.working_dir)
    log.info("tmux session created", session=session_uuid)
    return CreateSessionResponse(attach_command=attach_command)


class SessionAliveResponse(BaseModel):
    alive: bool


@app.get("/sessions/alive")
def session_alive(attach_command: str = Query(...)) -> SessionAliveResponse:
    return SessionAliveResponse(alive=is_tmux_alive(attach_command))


@app.post("/sessions/kill", status_code=204)
def kill_session(attach_command: str = Query(...)):
    name = attach_command.split()[-1] if attach_command else ""
    alive_before = is_tmux_alive(attach_command) if attach_command else False
    kill_tmux_session(attach_command)
    alive_after = is_tmux_alive(attach_command) if attach_command else False
    log.info("tmux session kill", session=name, was_alive=alive_before, still_alive=alive_after)


@app.post("/sessions/renew", response_model=CreateSessionResponse)
def renew_session(working_dir: str = Query(...), old_attach_command: str = Query(None)):
    # Kill the old session if it exists
    if old_attach_command:
        try:
            kill_tmux_session(old_attach_command)
            log.info("old tmux session killed before renew", attach_command=old_attach_command)
        except Exception:
            pass
    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=working_dir)
    return CreateSessionResponse(attach_command=attach_command)


# --- Git operations ---

class PushRequest(BaseModel):
    repo_path: str
    url: str
    refspec: str
    access_token: str | None = None


@app.post("/git/push")
def push(body: PushRequest):
    try:
        msg = git_push(body.repo_path, body.url, body.refspec, body.access_token)
        return {"message": msg}
    except subprocess.CalledProcessError as e:
        raise HTTPException(400, e.stderr.strip() or str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "push timed out")


@app.get("/git/diff")
def get_diff(repo_path: str = Query(...), from_hash: str = Query(...), to_hash: str = Query(...)):
    try:
        return PlainTextResponse(git_diff(repo_path, from_hash, to_hash))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "diff timed out")


@app.get("/git/tree")
def get_tree(repo_path: str = Query(...), hash: str = Query(...)):
    try:
        return git_tree(repo_path, hash)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "timed out")


@app.get("/git/file")
def get_file(repo_path: str = Query(...), hash: str = Query(...), path: str = Query(...)):
    try:
        return PlainTextResponse(git_show_file(repo_path, hash, path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "timed out")


# --- Workdir operations ---

@app.get("/workdir/files")
def list_workdir(root: str = Query(...)):
    if not os.path.isdir(root):
        raise HTTPException(404, "Directory not found")
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            files.append(os.path.relpath(full, root))
    return sorted(files)


@app.get("/workdir/file")
def read_workdir_file(root: str = Query(...), path: str = Query(...)):
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root)):
        raise HTTPException(400, "Invalid path")
    try:
        return PlainTextResponse(open(full).read())
    except Exception as e:
        raise HTTPException(400, str(e))


class WriteFileRequest(BaseModel):
    root: str
    path: str
    content: str


@app.put("/workdir/file", status_code=204)
def write_workdir_file(body: WriteFileRequest):
    full = os.path.realpath(os.path.join(body.root, body.path))
    if not full.startswith(os.path.realpath(body.root)):
        raise HTTPException(400, "Invalid path")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w").write(body.content)


@app.post("/workdir/commit", status_code=204)
def commit_workdir(root: str = Query(...)):
    try:
        subprocess.run(["git", "-C", root, "add", "-A"], check=True, timeout=10)
        result = subprocess.run(
            ["git", "-C", root, "diff", "--cached", "--quiet"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "-C", root,
                 "-c", "user.name=coresearch",
                 "-c", "user.email=coresearch@local",
                 "commit", "-m", "branching edit"],
                check=True, timeout=10,
            )
    except subprocess.CalledProcessError as e:
        raise HTTPException(400, str(e))


# --- Visual file serving ---

@app.get("/visuals/file")
def get_visual_file(path: str = Query(...)):
    if not os.path.isfile(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path)


# --- Terminal WebSocket ---

def _set_pty_size(fd: int, rows: int, cols: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket, attach_command: str):
    await websocket.accept()

    cmd = attach_command.split()
    master_fd, slave_fd = pty.openpty()

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
