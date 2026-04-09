"""Runner resource: list, list-branches-on-runner, rename."""
from fastapi import APIRouter, HTTPException

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import RenameRunnerRequest

from controlplane.routers.branches import branch_columns, build_branch_response

router = APIRouter(tags=["runners"])


@router.get("/runners")
def get_runners():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, url, status, capabilities, registered_at, last_heartbeat FROM runners ORDER BY id")
        return cur.fetchall()


@router.get("/runners/{runner_id}/branches")
def get_runner_branches(runner_id: int):
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {branch_columns()},
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
            results.append(build_branch_response(branch_data, session_data))
        return results


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
