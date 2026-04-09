"""Project resource: list, create."""
import uuid

from fastapi import APIRouter

from connections.postgres.connection import get_cursor
from shared.schemas import CreateProjectRequest

router = APIRouter(tags=["projects"])


@router.get("/projects")
def get_projects():
    with get_cursor() as cur:
        cur.execute("SELECT id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root FROM projects ORDER BY created_at DESC")
        return cur.fetchall()


@router.post("/projects", status_code=201)
def post_project(body: CreateProjectRequest):
    project_uuid = str(uuid.uuid4())
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO projects (name, uuid, user_id, llm_provider, llm_model, project_root)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root""",
            (body.name, project_uuid, body.user_id, body.llm_provider, body.llm_model, f"project_{project_uuid}"),
        )
        return cur.fetchone()
