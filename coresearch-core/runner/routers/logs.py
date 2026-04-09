"""Streams the runner's log ring buffer over a websocket."""
import asyncio

from fastapi import APIRouter, WebSocket

from runner import log

router = APIRouter()


@router.websocket("/ws/logs")
async def log_stream(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
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
