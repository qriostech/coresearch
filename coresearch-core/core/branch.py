import os
import shutil
import uuid
import subprocess

from connections.postgres.connection import get_cursor
from schemas.branch import Branch
from schemas.session import Session
from core.runners.tmux import create_tmux_session


def _build_branch_with_session(branch_row, session_row=None) -> Branch:
    session = Session(**session_row) if session_row else None
    return Branch(**branch_row, session=session)


def create_branch(
    seed_id: int,
    name: str,
    runner: str = "tmux",
    agent: str = "default",
    description: str = "",
) -> Branch:
    branch_uuid = str(uuid.uuid4())

    with get_cursor() as cur:
        cur.execute("SELECT path, repository_url, branch, commit, access_token FROM seeds WHERE id = %s", (seed_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Seed {seed_id} not found")

        seed_path = row["path"]
        repository_url = row["repository_url"]
        seed_branch = row["branch"]
        seed_commit = row["commit"]
        access_token = row["access_token"]

    branch_dir = os.path.join(seed_path, name)

    token = access_token or os.environ.get("GITHUB_TOKEN")
    clone_url = repository_url
    if token and "://" in repository_url:
        scheme, rest = repository_url.split("://", 1)
        clone_url = f"{scheme}://oauth2:{token}@{rest}"

    git_branch = f"coresearch/{name}-{branch_uuid[:8]}"

    subprocess.run(["git", "clone", "--branch", seed_branch, clone_url, branch_dir], check=True, timeout=120)
    subprocess.run(["git", "-C", branch_dir, "checkout", "-b", git_branch, seed_commit], check=True, timeout=10)

    result = subprocess.run(
        ["git", "-C", branch_dir, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    commit = result.stdout.strip()

    attach_command = create_tmux_session(branch_uuid, working_dir=branch_dir)
    sync_command = f"rsync -av {branch_dir}/"

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO branches (uuid, seed_id, name, description, path, sync_command, commit, git_branch)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, uuid, seed_id, name, description, path, sync_command, commit, git_branch, created_at, parent_branch_id, parent_iteration_hash
            """,
            (branch_uuid, seed_id, name, description, branch_dir, sync_command, commit, git_branch),
        )
        branch_row = cur.fetchone()

        cur.execute(
            """
            INSERT INTO sessions (branch_id, runner, attach_command, agent, status, started_at)
            VALUES (%s, %s, %s, %s, 'active', now())
            RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at
            """,
            (branch_row["id"], runner, attach_command, agent),
        )
        session_row = cur.fetchone()

    return _build_branch_with_session(branch_row, session_row)


def fork_branch(
    branch_id: int,
    name: str,
    iteration_hash: str,
    runner: str = "tmux",
    agent: str = "default",
    description: str = "",
) -> Branch:
    branch_uuid = str(uuid.uuid4())

    with get_cursor() as cur:
        cur.execute("SELECT seed_id, path FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Branch {branch_id} not found")
        source_path = row["path"]
        seed_id = row["seed_id"]

        cur.execute("SELECT path FROM seeds WHERE id = %s", (seed_id,))
        seed_row = cur.fetchone()
        if seed_row is None:
            raise ValueError(f"Seed {seed_id} not found")
        seed_path = seed_row["path"]

    branch_dir = os.path.join(seed_path, name)
    git_branch = f"coresearch/{name}-{branch_uuid[:8]}"

    subprocess.run(["git", "clone", source_path, branch_dir], check=True, timeout=120)
    subprocess.run(["git", "-C", branch_dir, "checkout", "-b", git_branch, iteration_hash], check=True, timeout=10)

    result = subprocess.run(
        ["git", "-C", branch_dir, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    commit = result.stdout.strip()

    attach_command = create_tmux_session(branch_uuid, working_dir=branch_dir)
    sync_command = f"rsync -av {branch_dir}/"

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO branches (uuid, seed_id, name, description, path, sync_command, commit, git_branch, parent_branch_id, parent_iteration_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, uuid, seed_id, name, description, path, sync_command, commit, git_branch, created_at, parent_branch_id, parent_iteration_hash
            """,
            (branch_uuid, seed_id, name, description, branch_dir, sync_command, commit, git_branch, branch_id, iteration_hash),
        )
        branch_row = cur.fetchone()

        cur.execute(
            """
            INSERT INTO sessions (branch_id, runner, attach_command, agent, status, started_at)
            VALUES (%s, %s, %s, %s, 'active', now())
            RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at
            """,
            (branch_row["id"], runner, attach_command, agent),
        )
        session_row = cur.fetchone()

    return _build_branch_with_session(branch_row, session_row)


def is_session_alive(branch_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if row is None:
        return False
    session_name = row["attach_command"].split()[-1]
    result = subprocess.run(["tmux", "has-session", "-t", session_name], capture_output=True, timeout=5)
    return result.returncode == 0


def kill_branch_session(branch_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("SELECT id, attach_command FROM sessions WHERE branch_id = %s", (branch_id,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Session for branch {branch_id} not found")
    session_name = row["attach_command"].split()[-1]
    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE sessions SET status = 'killed', ended_at = now() WHERE id = %s",
            (row["id"],),
        )


def renew_branch_session(branch_id: int) -> Branch:
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.id, b.uuid, b.seed_id, b.name, b.description, b.path, b.sync_command,
                      b.commit, b.git_branch, b.created_at, b.parent_branch_id, b.parent_iteration_hash
               FROM branches b WHERE b.id = %s AND NOT b.deleted""",
            (branch_id,),
        )
        branch_row = cur.fetchone()
        if branch_row is None:
            raise ValueError(f"Branch {branch_id} not found")

    attach_command = create_tmux_session(str(uuid.uuid4()), working_dir=branch_row["path"])

    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE sessions SET attach_command = %s, status = 'active', started_at = now(), ended_at = NULL
            WHERE branch_id = %s
            RETURNING id, branch_id, runner, attach_command, agent, status, started_at, ended_at, created_at
            """,
            (attach_command, branch_id),
        )
        session_row = cur.fetchone()

    return _build_branch_with_session(branch_row, session_row)


def list_branches(seed_id: int) -> list[Branch]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT b.id, b.uuid, b.seed_id, b.name, b.description, b.path, b.sync_command,
                      b.commit, b.git_branch, b.created_at, b.parent_branch_id, b.parent_iteration_hash,
                      s.id AS s_id, s.branch_id AS s_branch_id, s.runner, s.attach_command, s.agent,
                      s.status, s.started_at, s.ended_at, s.created_at AS s_created_at
               FROM branches b
               LEFT JOIN sessions s ON s.branch_id = b.id
               WHERE b.seed_id = %s AND NOT b.deleted
               ORDER BY b.created_at DESC""",
            (seed_id,),
        )
        results = []
        for row in cur.fetchall():
            branch_data = {
                "id": row["id"], "uuid": row["uuid"], "seed_id": row["seed_id"],
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
            results.append(_build_branch_with_session(branch_data, session_data))
        return results


def delete_branch(branch_id: int) -> None:
    with get_cursor() as cur:
        cur.execute("SELECT id, path, seed_id FROM branches WHERE id = %s AND NOT deleted", (branch_id,))
        root = cur.fetchone()
        if root is None:
            raise ValueError(f"Branch {branch_id} not found")

        # Collect full subtree (BFS)
        seed_id = root["seed_id"]
        to_visit = [root]
        all_branches = [root]
        visited = {root["id"]}

        while to_visit:
            current = to_visit.pop(0)
            cur.execute(
                "SELECT id, path, seed_id FROM branches WHERE parent_branch_id = %s AND NOT deleted",
                (current["id"],),
            )
            for child in cur.fetchall():
                if child["id"] not in visited:
                    visited.add(child["id"])
                    all_branches.append(child)
                    to_visit.append(child)

        all_ids = [b["id"] for b in all_branches]

        # Kill tmux sessions
        cur.execute("SELECT attach_command FROM sessions WHERE branch_id = ANY(%s)", (all_ids,))
        for s in cur.fetchall():
            session_name = s["attach_command"].split()[-1]
            subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)

        # Mark sessions as killed
        cur.execute(
            "UPDATE sessions SET status = 'killed', ended_at = now() WHERE branch_id = ANY(%s)",
            (all_ids,),
        )

        # Soft-delete branches
        cur.execute("UPDATE branches SET deleted = TRUE WHERE id = ANY(%s)", (all_ids,))

        # Move working directories to .fordeletion
        cur.execute("SELECT path FROM seeds WHERE id = %s", (seed_id,))
        seed_row = cur.fetchone()
        if seed_row:
            fordeletion = os.path.join(seed_row["path"], ".fordeletion")
            os.makedirs(fordeletion, exist_ok=True)
            for b in all_branches:
                if os.path.isdir(b["path"]):
                    dest = os.path.join(fordeletion, os.path.basename(b["path"]))
                    shutil.move(b["path"], dest)
