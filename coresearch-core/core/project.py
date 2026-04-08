import os
import uuid
from dotenv import load_dotenv

from connections.postgres.connection import get_cursor
from schemas.project import Project

load_dotenv(os.path.join(os.path.dirname(__file__), "../../config.env"))


def create_project(
    name: str,
    user_id: int = 1,
    llm_provider: str = "default_llm",
    llm_model: str = "default_model",
) -> Project:
    """
    Creates a new project: makes a directory on disk and inserts a row into the DB.

    Returns the created Project.
    """
    project_root = os.path.expanduser(os.getenv("PROJECT_ROOT", os.getenv("SESSION_ROOT", "~/.coresearch/sessions")))
    project_uuid = str(uuid.uuid4())
    project_dir = os.path.join(project_root, f"{name}_{project_uuid}")
    os.makedirs(project_dir, exist_ok=True)

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (name, uuid, user_id, llm_provider, llm_model, project_root)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root
            """,
            (name, project_uuid, user_id, llm_provider, llm_model, project_dir),
        )
        row = cur.fetchone()

    return Project(**row)


def list_projects() -> list[Project]:
    with get_cursor() as cur:
        cur.execute("SELECT id, name, uuid, user_id, created_at, updated_at, llm_provider, llm_model, project_root FROM projects ORDER BY created_at DESC")
        return [Project(**row) for row in cur.fetchall()]
