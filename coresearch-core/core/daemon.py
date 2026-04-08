import asyncio
import json
import os
from pathlib import Path

from connections.postgres.connection import get_cursor

POLL_INTERVAL = 5  # seconds
METRICS_FORMATS = {".json"}
VISUAL_FORMATS = {".png", ".svg", ".html", ".jpg", ".jpeg", ".gif"}


async def run():
    """Entry point — polls branch directories indefinitely."""
    print("[daemon] started")
    while True:
        try:
            await asyncio.to_thread(_scan_all_branches)
        except Exception as e:
            print(f"[daemon] error: {e}")
        await asyncio.sleep(POLL_INTERVAL)


def _scan_all_branches():
    with get_cursor() as cur:
        cur.execute("SELECT id, path FROM branches WHERE NOT deleted")
        branches = cur.fetchall()
    for branch in branches:
        _scan_branch(branch["id"], branch["path"])


def _scan_branch(branch_id: int, branch_path: str):
    iterations_dir = Path(branch_path) / ".coresearch" / "iterations"
    if not iterations_dir.is_dir():
        return

    for iter_dir in sorted(iterations_dir.iterdir()):
        if not iter_dir.is_dir():
            continue
        iteration_hash = iter_dir.name
        iteration_id = _get_or_create_iteration(branch_id, iteration_hash)

        metrics_dir = iter_dir / "metrics"
        if metrics_dir.is_dir():
            _scan_metrics(iteration_id, metrics_dir)

        visual_dir = iter_dir / "visual"
        if visual_dir.is_dir():
            _scan_visuals(iteration_id, visual_dir)


def _get_or_create_iteration(branch_id: int, hash: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO iterations (branch_id, hash, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (branch_id, hash) DO NOTHING
            RETURNING id
            """,
            (branch_id, hash, hash),
        )
        row = cur.fetchone()
        if row:
            print(f"[daemon] new iteration {hash} on branch {branch_id}")
            return row["id"]

        cur.execute(
            "SELECT id FROM iterations WHERE branch_id = %s AND hash = %s",
            (branch_id, hash),
        )
        return cur.fetchone()["id"]


def _scan_metrics(iteration_id: int, metrics_dir: Path):
    for file in metrics_dir.iterdir():
        if not file.is_file() or file.suffix not in METRICS_FORMATS:
            continue
        try:
            data = json.loads(file.read_text())
        except Exception as e:
            print(f"[daemon] failed to parse {file}: {e}")
            continue

        with get_cursor() as cur:
            for key, value in data.items():
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                cur.execute(
                    """
                    INSERT INTO iteration_metrics (iteration_id, key, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (iteration_id, key)
                    DO UPDATE SET value = EXCLUDED.value, recorded_at = now()
                    """,
                    (iteration_id, key, numeric),
                )


def _scan_visuals(iteration_id: int, visual_dir: Path):
    for file in visual_dir.iterdir():
        if not file.is_file() or file.suffix.lower() not in VISUAL_FORMATS:
            continue
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO iteration_visuals (iteration_id, filename, format, path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (iteration_id, filename) DO NOTHING
                """,
                (iteration_id, file.name, file.suffix.lstrip("."), str(file)),
            )
