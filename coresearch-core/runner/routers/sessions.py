"""Tmux session lifecycle and the terminal websocket."""
import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from shared.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionAliveResponse,
)

from runner import log
from runner.core.tmux import create_tmux_session, is_tmux_alive, kill_tmux_session

router = APIRouter()


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest):
    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=body.working_dir)
    log.info("tmux session created", session=session_uuid)
    return CreateSessionResponse(attach_command=attach_command)


@router.get("/sessions/alive")
def session_alive(attach_command: str = Query(...)) -> SessionAliveResponse:
    return SessionAliveResponse(alive=is_tmux_alive(attach_command))


@router.post("/sessions/kill", status_code=204)
def kill_session(attach_command: str = Query(...)):
    name = attach_command.split()[-1] if attach_command else ""
    alive_before = is_tmux_alive(attach_command) if attach_command else False
    kill_tmux_session(attach_command)
    alive_after = is_tmux_alive(attach_command) if attach_command else False
    log.info("tmux session kill", session=name, was_alive=alive_before, still_alive=alive_after)


@router.post("/sessions/renew", response_model=CreateSessionResponse)
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


# --- Terminal WebSocket ---

def _set_pty_size(fd: int, rows: int, cols: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@router.websocket("/ws/terminal")
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
