"""Cory container HTTP API.

Small FastAPI app that runs alongside the postgres MCP server inside the cory
container. The controlplane calls these endpoints to create and destroy cory
tmux sessions, mirroring the way it talks to the runner for branch sessions.

Default working directory for new sessions is /home/coresearch (the runtime
user's home), so claude/codex started in the session pick up the user-level
.claude.json with the pre-approved cory MCP server.
"""
import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from shared.middleware import RequestLoggingMiddleware
from shared.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionAliveResponse,
)

from cory import log
from cory.tmux import create_tmux_session, is_tmux_alive, kill_tmux_session

DEFAULT_WORKING_DIR = os.environ.get("CORY_WORKING_DIR", "/home/coresearch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting", app=app.title, working_dir=DEFAULT_WORKING_DIR)
    yield
    log.info("shutting down", app=app.title)


app = FastAPI(title="Coresearch Cory", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware, logger=log, generate_request_id=False)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest):
    working_dir = body.working_dir or DEFAULT_WORKING_DIR
    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=working_dir)
    log.info("cory tmux session created", session=session_uuid, working_dir=working_dir)
    return CreateSessionResponse(attach_command=attach_command)


@app.get("/sessions/alive")
def session_alive(attach_command: str = Query(...)) -> SessionAliveResponse:
    return SessionAliveResponse(alive=is_tmux_alive(attach_command))


@app.post("/sessions/kill", status_code=204)
def kill_session(attach_command: str = Query(...)):
    name = attach_command.split()[-1] if attach_command else ""
    alive_before = is_tmux_alive(attach_command) if attach_command else False
    kill_tmux_session(attach_command)
    alive_after = is_tmux_alive(attach_command) if attach_command else False
    log.info("cory tmux session kill", session=name, was_alive=alive_before, still_alive=alive_after)


# --- Terminal WebSocket -----------------------------------------------------
#
# Mirrors runner/routers/sessions.py::terminal_ws verbatim. Both endpoints
# spawn the supplied attach_command (typically `tmux attach-session -t <uuid>`)
# under a fresh PTY and bridge bytes between the PTY and the websocket. Kept
# as a copy rather than a shared module because the cory container does not
# import from the runner package.

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
