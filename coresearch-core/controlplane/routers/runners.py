"""Runner resource: list, list-branches-on-runner, rename."""
from fastapi import APIRouter, HTTPException

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import Branch, RenameRunnerRequest, Runner

from controlplane.routers.branches import BRANCH_WITH_SESSION_SELECT, row_to_branch

router = APIRouter(tags=["runners"])


@router.get("/runners", response_model=list[Runner])
def get_runners():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status, capabilities, registered_at, last_heartbeat FROM runners ORDER BY id")
        return cur.fetchall()


@router.get("/runners/{runner_id}/branches", response_model=list[Branch])
def get_runner_branches(runner_id: int):
    with get_cursor() as cur:
        cur.execute(
            f"{BRANCH_WITH_SESSION_SELECT} WHERE b.runner_id = %s AND NOT b.deleted ORDER BY b.created_at DESC",
            (runner_id,),
        )
        return [row_to_branch(row) for row in cur.fetchall()]


@router.patch("/runners/{runner_id}", status_code=204)
def rename_runner(runner_id: int, body: RenameRunnerRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE runners SET name = %s WHERE id = %s RETURNING id",
            (body.name, runner_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Runner not found")
    event_bus.emit("runner.registered", runner_id=runner_id, runner_name=body.name)
