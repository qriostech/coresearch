import os
import shutil
import subprocess
import uuid

from connections.postgres.connection import get_cursor
from schemas.seed import Seed
from core.branch import delete_branch


def _inject_token(url: str, token: str | None) -> str:
    if token and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://oauth2:{token}@{rest}"
    return url


def _detect_default_branch(auth_url: str) -> tuple[str, str]:
    """Returns (branch_name, commit) for the remote's HEAD."""
    result = subprocess.run(
        ["git", "ls-remote", "--symref", auth_url, "HEAD"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    branch = "main"
    commit = None
    for line in result.stdout.strip().splitlines():
        if line.startswith("ref:"):
            # "ref: refs/heads/master\tHEAD"
            branch = line.split("refs/heads/")[-1].split("\t")[0]
        elif "HEAD" in line:
            commit = line.split()[0]
    if not commit:
        raise ValueError("Could not detect default branch")
    return branch, commit


def _resolve_branch_and_commit(repository_url: str, requested_branch: str | None, requested_commit: str | None, access_token: str | None = None) -> tuple[str, str]:
    """
    Resolves the branch and commit to use for a seed.
    Falls back to the remote's default branch + latest commit if the requested values are absent or invalid.
    """
    token = access_token or os.environ.get("GITHUB_TOKEN")
    auth_url = _inject_token(repository_url, token)

    if requested_branch:
        result = subprocess.run(
            ["git", "ls-remote", auth_url, f"refs/heads/{requested_branch}"],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in result.stdout.strip().splitlines() if l]
        if lines:
            branch = requested_branch
            remote_commit = lines[0].split()[0]
        else:
            # Requested branch not found — fall back to default
            branch, remote_commit = _detect_default_branch(auth_url)
    else:
        branch, remote_commit = _detect_default_branch(auth_url)

    # If a specific commit was requested, accept it if it looks like a valid sha
    if requested_commit and len(requested_commit) >= 7 and all(c in "0123456789abcdefABCDEF" for c in requested_commit):
        return branch, requested_commit

    return branch, remote_commit


def create_seed(project_id: int, name: str, repository_url: str,
                branch: str | None = None, commit: str | None = None,
                access_token: str | None = None) -> Seed:
    """
    Creates a new seed: makes a directory under the project root and inserts a row into the DB.
    Resolves branch/commit with fallback to main + latest commit.
    Returns the created Seed.
    """
    seed_uuid = str(uuid.uuid4())
    resolved_branch, resolved_commit = _resolve_branch_and_commit(repository_url, branch, commit, access_token)

    with get_cursor() as cur:
        cur.execute("SELECT project_root FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Project {project_id} not found")
        seed_dir = os.path.join(row["project_root"], f"{name}_{seed_uuid}")
        os.makedirs(seed_dir, exist_ok=True)

        cur.execute(
            """
            INSERT INTO seeds (uuid, project_id, name, repository_url, path, branch, commit, access_token)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, uuid, project_id, name, repository_url, path, branch, commit,
                      (access_token IS NOT NULL AND access_token != '') AS has_access_token, created_at
            """,
            (seed_uuid, project_id, name, repository_url, seed_dir, resolved_branch, resolved_commit, access_token or None),
        )
        row = cur.fetchone()

    return Seed(**row)


def list_seeds(project_id: int) -> list[Seed]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, uuid, project_id, name, repository_url, path, branch, commit,
                   (access_token IS NOT NULL AND access_token != '') AS has_access_token, created_at
            FROM seeds WHERE project_id = %s AND NOT deleted ORDER BY created_at DESC
            """,
            (project_id,)
        )
        return [Seed(**row) for row in cur.fetchall()]


def delete_seed(seed_id: int) -> None:
    """
    Soft-deletes a seed and all its branches.
    Moves the seed directory to {project_root}/.fordeletion/.
    """
    with get_cursor() as cur:
        cur.execute("SELECT id, path, project_id FROM seeds WHERE id = %s AND NOT deleted", (seed_id,))
        seed = cur.fetchone()
        if seed is None:
            raise ValueError(f"Seed {seed_id} not found")

        # Soft-delete all branches under this seed
        cur.execute("SELECT id FROM branches WHERE seed_id = %s AND NOT deleted", (seed_id,))
        for row in cur.fetchall():
            delete_branch(row["id"])

        # Soft-delete the seed
        cur.execute("UPDATE seeds SET deleted = TRUE WHERE id = %s", (seed_id,))

        # Move working directory
        cur.execute("SELECT project_root FROM projects WHERE id = %s", (seed["project_id"],))
        project = cur.fetchone()
        if project and os.path.isdir(seed["path"]):
            fordeletion = os.path.join(project["project_root"], ".fordeletion")
            os.makedirs(fordeletion, exist_ok=True)
            shutil.move(seed["path"], os.path.join(fordeletion, os.path.basename(seed["path"])))
