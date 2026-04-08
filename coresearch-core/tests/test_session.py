import os
import shutil
import pytest

from connections.postgres.connection import get_cursor
from core.project import create_project
from schemas.project import Project


@pytest.fixture(autouse=True)
def cleanup_projects():
    created_ids = []
    created_dirs = []
    yield created_ids, created_dirs
    # Remove DB rows
    if created_ids:
        with get_cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = ANY(%s)", (created_ids,))
    # Remove directories
    for d in created_dirs:
        if os.path.isdir(d):
            shutil.rmtree(d)


def test_create_project_returns_project(cleanup_projects):
    ids, dirs = cleanup_projects
    project = create_project("test")
    ids.append(project.id)
    dirs.append(project.project_root)

    assert isinstance(project, Project)
    assert project.name == "test"
    assert project.user_id == 1
    assert project.llm_provider == "default_llm"
    assert project.llm_model == "default_model"
    assert project.uuid is not None


def test_create_project_creates_directory(cleanup_projects):
    ids, dirs = cleanup_projects
    project = create_project("dirtest")
    ids.append(project.id)
    dirs.append(project.project_root)

    assert os.path.isdir(project.project_root)
    assert os.path.basename(project.project_root).startswith("dirtest_")


def test_create_project_writes_to_db(cleanup_projects):
    ids, dirs = cleanup_projects
    project = create_project("dbtest")
    ids.append(project.id)
    dirs.append(project.project_root)

    with get_cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project.id,))
        row = cur.fetchone()

    assert row is not None
    assert row["name"] == "dbtest"
    assert row["user_id"] == 1
    assert row["uuid"] == project.uuid


def test_create_project_unique(cleanup_projects):
    ids, dirs = cleanup_projects
    s1 = create_project("test")
    s2 = create_project("test")
    ids.extend([s1.id, s2.id])
    dirs.extend([s1.project_root, s2.project_root])

    assert s1.uuid != s2.uuid
    assert s1.project_root != s2.project_root


def test_create_project_custom_llm(cleanup_projects):
    ids, dirs = cleanup_projects
    project = create_project("llmtest", llm_provider="openai", llm_model="gpt-4o")
    ids.append(project.id)
    dirs.append(project.project_root)

    assert project.llm_provider == "openai"
    assert project.llm_model == "gpt-4o"
