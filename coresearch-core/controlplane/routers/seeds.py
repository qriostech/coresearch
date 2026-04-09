"""Seed resource: list, create, delete, create-from-iteration."""
import uuid

from fastapi import APIRouter, HTTPException

from connections.postgres.connection import get_cursor
from shared.events import event_bus
from shared.schemas import CreateSeedRequest, SeedFromIterationRequest

from controlplane.routers.branches import delete_branch_tree
from controlplane.runner_proxy import (
    any_active_runner_id,
    get_runner_id_for_branch,
    runner_call,
)

router = APIRouter(tags=["seeds"])


@router.get("/projects/{project_id}/seeds")
def get_seeds(project_id: int):
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, uuid, project_id, name, repository_url, branch, commit, created_at
               FROM seeds WHERE project_id = %s AND NOT deleted ORDER BY created_at DESC""",
            (project_id,),
        )
        return cur.fetchall()


@router.post("/projects/{project_id}/seeds", status_code=201)
def post_seed(project_id: int, body: CreateSeedRequest):
    with get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Project not found")

    seed_uuid = str(uuid.uuid4())

    # Resolve branch/commit via any active runner (just a git ls-remote)
    runner_id = any_active_runner_id()
    if runner_id:
        resp = runner_call(runner_id, "POST", "/resolve-ref", json={
            "repository_url": body.repository_url,
            "branch": body.branch,
            "commit": body.commit,
            "access_token": body.access_token,
        })
        result = resp.json()
        resolved_branch = result["branch"]
        resolved_commit = result["commit"]
    else:
        # No runners available — use provided values or defaults
        resolved_branch = body.branch or "main"
        resolved_commit = body.commit or ""

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO seeds (uuid, project_id, name, repository_url, branch, commit, access_token)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, project_id, name, repository_url, branch, commit, created_at""",
            (seed_uuid, project_id, body.name, body.repository_url, resolved_branch, resolved_commit, body.access_token or None),
        )
        row = cur.fetchone()

    event_bus.emit("seed.created", project_id=project_id, seed_id=row["id"])
    return row


@router.delete("/seeds/{seed_id}", status_code=204)
def delete_seed_endpoint(seed_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT id FROM seeds WHERE id = %s AND NOT deleted", (seed_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Seed not found")
        cur.execute("SELECT id FROM branches WHERE seed_id = %s AND NOT deleted", (seed_id,))
        branch_ids = [row["id"] for row in cur.fetchall()]

    # Delete all branches (each handles its own runner calls)
    for bid in branch_ids:
        delete_branch_tree(bid)

    with get_cursor() as cur:
        cur.execute("UPDATE seeds SET deleted = TRUE WHERE id = %s", (seed_id,))

    event_bus.emit("seed.deleted", seed_id=seed_id)


@router.post("/projects/{project_id}/seeds/from-iteration", status_code=201)
def seed_from_iteration(project_id: int, body: SeedFromIterationRequest):
    runner_id = get_runner_id_for_branch(body.branch_id)
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.path, b.git_branch, b.seed_id, s.repository_url, s.access_token
               FROM branches b JOIN seeds s ON s.id = b.seed_id
               WHERE b.id = %s AND NOT b.deleted""",
            (body.branch_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Branch not found")
    if not row["git_branch"]:
        raise HTTPException(400, "Branch has no git_branch set")

    refspec = f"{body.iteration_hash}:refs/heads/{row['git_branch']}"
    try:
        runner_call(runner_id, "POST", "/git/push", json={
            "repo_path": row["path"],
            "url": row["repository_url"],
            "refspec": refspec,
            "access_token": row.get("access_token"),
        })
    except HTTPException:
        pass  # already on remote

    with get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Project not found")

    seed_uuid = str(uuid.uuid4())

    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO seeds (uuid, project_id, name, repository_url, branch, commit)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, uuid, project_id, name, repository_url, branch, commit, created_at""",
            (seed_uuid, project_id, body.name, row["repository_url"],
             row["git_branch"], body.iteration_hash),
        )
        return cur.fetchone()
