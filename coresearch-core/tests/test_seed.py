import os
import pytest

from connections.postgres.connection import get_cursor
from core.project import create_project
from core.seed import create_seed
from schemas.seed import Seed


@pytest.fixture()
def project():
    import shutil, os
    s = create_project("seed-test-project")
    seed_ids = []
    yield s, seed_ids
    with get_cursor() as cur:
        if seed_ids:
            cur.execute("DELETE FROM seeds WHERE id = ANY(%s)", (seed_ids,))
        cur.execute("DELETE FROM projects WHERE id = %s", (s.id,))
    if os.path.isdir(s.project_root):
        shutil.rmtree(s.project_root)


def test_create_seed_returns_seed(project):
    s, seed_ids = project
    seed = create_seed(s.id, "my-seed", "https://github.com/example/repo")
    seed_ids.append(seed.id)

    assert isinstance(seed, Seed)
    assert seed.name == "my-seed"
    assert seed.repository_url == "https://github.com/example/repo"
    assert seed.project_id == s.id
    assert seed.uuid is not None
    assert os.path.isdir(seed.path)
    assert os.path.basename(seed.path).startswith("my-seed_")


def test_create_seed_writes_to_db(project):
    s, seed_ids = project
    seed = create_seed(s.id, "db-seed", "https://github.com/example/repo")
    seed_ids.append(seed.id)

    with get_cursor() as cur:
        cur.execute("SELECT * FROM seeds WHERE id = %s", (seed.id,))
        row = cur.fetchone()

    assert row is not None
    assert row["name"] == "db-seed"
    assert row["uuid"] == seed.uuid
    assert row["project_id"] == s.id


def test_create_seed_unique_uuid(project):
    s, seed_ids = project
    s1 = create_seed(s.id, "seed-a", "https://github.com/example/repo")
    s2 = create_seed(s.id, "seed-b", "https://github.com/example/repo")
    seed_ids.extend([s1.id, s2.id])

    assert s1.uuid != s2.uuid
