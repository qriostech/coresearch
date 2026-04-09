"""Coresearch runner FastAPI app.

Slim entrypoint: instantiates the FastAPI app, configures middleware, launches
background tasks in lifespan, and registers routers. All actual handlers live
under ``runner/routers/``.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.middleware import RequestLoggingMiddleware

from runner import log
from runner.config import RUNNER_NAME, STORAGE_ROOT
from runner.core.daemon import Daemon
from runner.heartbeat import start_heartbeat, stop_heartbeat
from runner.routers import branches, git, health, logs as logs_router, sessions, visuals, workdir

daemon = Daemon()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting", app=app.title, storage_root=STORAGE_ROOT, runner_name=RUNNER_NAME)
    controlplane_url = os.environ.get("CONTROLPLANE_URL", "http://controlplane:8000")
    daemon.start(controlplane_url)
    start_heartbeat(controlplane_url)
    yield
    stop_heartbeat()
    daemon.stop()
    log.info("shutting down", app=app.title)


app = FastAPI(title="Coresearch Runner", lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware, logger=log, generate_request_id=False)

for module in (health, branches, sessions, git, workdir, visuals, logs_router):
    app.include_router(module.router)
