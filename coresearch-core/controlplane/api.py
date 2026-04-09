"""Coresearch control plane FastAPI app.

Slim entrypoint: instantiates the FastAPI app, configures middleware, launches
background tasks in lifespan, and registers routers. All actual handlers live
under ``controlplane/routers/``.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.middleware import RequestLoggingMiddleware

from controlplane import log
from controlplane.background import stale_runner_check
from controlplane.routers import branches, internal, iterations, projects, runners, seeds, websockets


@asynccontextmanager
async def lifespan(_app: FastAPI):
    del _app  # required by FastAPI lifespan contract but unused
    log.info("starting controlplane")
    stale_task = asyncio.create_task(stale_runner_check())
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

for module in (runners, projects, seeds, branches, iterations, websockets, internal):
    app.include_router(module.router)
