import os
import shutil
import pytest

from connections.postgres.connection import get_cursor
from core.project import create_project
from core.seed import create_seed
from core.branch import create_branch
from schemas.branch import Branch


@pytest.fixture()
def seed():
    s = create_project("branch-test-project")
    sd = create_seed(s.id, "blackgolem", "https://github.com/example/blackgolem.git")
    branch_ids = []
    yield sd, branch_ids
    with get_cursor() as cur:
        if branch_ids:
            cur.execute("DELETE FROM branches WHERE id = ANY(%s)", (branch_ids,))
        cur.execute("DELETE FROM seeds WHERE id = %s", (sd.id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (s.id,))
    if os.path.isdir(s.project_root):
        shutil.rmtree(s.project_root)


def test_create_branch_returns_branch(seed):
    sd, branch_ids = seed
    branch = create_branch(sd.id, "main")
    branch_ids.append(branch.id)

    assert isinstance(branch, Branch)
    assert branch.name == "main"
    assert branch.seed_id == sd.id
    assert branch.uuid is not None
    assert branch.commit != ""


def test_create_branch_creates_directory(seed):
    sd, branch_ids = seed
    branch = create_branch(sd.id, "experiment")
    branch_ids.append(branch.id)

    assert os.path.isdir(branch.path)
    assert branch.path == os.path.join(sd.path, "experiment")


def test_create_branch_clones_repo(seed):
    sd, branch_ids = seed
    branch = create_branch(sd.id, "clonetest")
    branch_ids.append(branch.id)

    assert os.path.isdir(os.path.join(branch.path, ".git"))


def test_create_branch_writes_to_db(seed):
    sd, branch_ids = seed
    branch = create_branch(sd.id, "dbtest")
    branch_ids.append(branch.id)

    with get_cursor() as cur:
        cur.execute("SELECT * FROM branches WHERE id = %s", (branch.id,))
        row = cur.fetchone()

    assert row is not None
    assert row["name"] == "dbtest"
    assert row["uuid"] == branch.uuid
    assert row["commit"] == branch.commit
