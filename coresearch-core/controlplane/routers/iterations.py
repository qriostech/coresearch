"""Iteration resource: list, update, comments, visuals."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from connections.postgres.connection import get_cursor
from shared.schemas import AddCommentRequest, UpdateIterationRequest

from controlplane.runner_proxy import get_runner_id_for_branch, runner_call

router = APIRouter(tags=["iterations"])


@router.get("/branches/{branch_id}/iterations")
def get_iterations(branch_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, branch_id, hash, name, description, hypothesis, analysis, guidelines_version, created_at FROM iterations WHERE branch_id = %s ORDER BY created_at",
            (branch_id,),
        )
        iterations = cur.fetchall()
        result = []
        for row in iterations:
            cur.execute(
                "SELECT id, iteration_id, key, value, recorded_at FROM iteration_metrics WHERE iteration_id = %s ORDER BY key",
                (row["id"],),
            )
            metrics = cur.fetchall()
            cur.execute(
                "SELECT id, iteration_id, filename, format, path, created_at FROM iteration_visuals WHERE iteration_id = %s ORDER BY filename",
                (row["id"],),
            )
            visuals = cur.fetchall()
            cur.execute(
                """SELECT c.id, c.iteration_id, c.user_id, u.name AS user_name, c.body, c.created_at
                   FROM iteration_comments c JOIN users u ON u.id = c.user_id
                   WHERE c.iteration_id = %s ORDER BY c.created_at""",
                (row["id"],),
            )
            comments = cur.fetchall()
            result.append({**dict(row), "metrics": [dict(m) for m in metrics], "visuals": [dict(v) for v in visuals], "comments": [dict(c) for c in comments]})
    return result


@router.patch("/iterations/{iteration_id}")
def update_iteration(iteration_id: int, body: UpdateIterationRequest):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE iterations SET description = %s WHERE id = %s RETURNING id",
            (body.description, iteration_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Iteration not found")


@router.post("/iterations/{iteration_id}/comments", status_code=201)
def add_comment(iteration_id: int, req: AddCommentRequest):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO iteration_comments (iteration_id, user_id, body)
               VALUES (%s, %s, %s) RETURNING id""",
            (iteration_id, req.user_id, req.body),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Iteration not found")
    return {"id": row["id"]}


@router.delete("/iterations/{iteration_id}/comments/{comment_id}", status_code=204)
def delete_comment(iteration_id: int, comment_id: int):
    with get_cursor() as cur:
        cur.execute(
            "DELETE FROM iteration_comments WHERE id = %s AND iteration_id = %s",
            (comment_id, iteration_id),
        )


@router.get("/iterations/{iteration_id}/visuals/{filename}")
def get_visual(iteration_id: int, filename: str):
    with get_cursor() as cur:
        cur.execute(
            """SELECT v.path, i.branch_id
               FROM iteration_visuals v JOIN iterations i ON i.id = v.iteration_id
               WHERE v.iteration_id = %s AND v.filename = %s""",
            (iteration_id, filename),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Visual not found")
    runner_id = get_runner_id_for_branch(row["branch_id"])
    resp = runner_call(runner_id, "GET", "/visuals/file", params={"path": row["path"]})
    return Response(content=resp.content, media_type=resp.headers.get("content-type", "application/octet-stream"))
