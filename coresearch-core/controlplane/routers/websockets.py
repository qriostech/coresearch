"""WebSocket endpoints: terminal proxy, event stream, log streams."""
import asyncio
from urllib.parse import quote

import websockets
from fastapi import APIRouter, Query, WebSocket

from connections.postgres.connection import get_cursor
from shared.events import event_bus

from .. import log
from ..runner_proxy import get_runner_url

router = APIRouter()


@router.websocket("/ws/branch/{branch_id}")
async def terminal_ws(websocket: WebSocket, branch_id: int):
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

    runner_url = get_runner_url(row["runner_id"])
    runner_ws_url = runner_url.replace("http://", "ws://").replace("https://", "wss://")
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


@router.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
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


@router.websocket("/ws/logs/controlplane")
async def controlplane_log_stream(websocket: WebSocket):
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


@router.websocket("/ws/logs/runner")
async def runner_log_stream(websocket: WebSocket, name: str = Query(None)):
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
