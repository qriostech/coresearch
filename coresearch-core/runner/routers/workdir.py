"""Workdir editor: list, read, write, commit."""
import os
import subprocess

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from shared.schemas import RunnerWriteFileRequest

router = APIRouter()


def _resolve_inside(root: str, path: str) -> str:
    """Join ``root`` and ``path`` and return the realpath, refusing anything that
    escapes ``root``. Uses os.path.commonpath rather than startswith because
    startswith is fooled by sibling directories that share a name prefix
    (e.g. root=/a/foo path=../foo2 → /a/foo2 which startswith /a/foo)."""
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root_real, path))
    try:
        if os.path.commonpath([full, root_real]) != root_real:
            raise HTTPException(400, "Invalid path")
    except ValueError:
        # commonpath raises if paths are on different drives or otherwise incomparable
        raise HTTPException(400, "Invalid path")
    return full


@router.get("/workdir/files")
def list_workdir(root: str = Query(...)):
    if not os.path.isdir(root):
        raise HTTPException(404, "Directory not found")
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            files.append(os.path.relpath(full, root))
    return sorted(files)


@router.get("/workdir/file")
def read_workdir_file(root: str = Query(...), path: str = Query(...)):
    full = _resolve_inside(root, path)
    try:
        with open(full) as f:
            return PlainTextResponse(f.read())
    except Exception as e:
        raise HTTPException(400, str(e))


@router.put("/workdir/file", status_code=204)
def write_workdir_file(body: RunnerWriteFileRequest):
    full = _resolve_inside(body.root, body.path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(body.content)


@router.post("/workdir/commit", status_code=204)
def commit_workdir(root: str = Query(...)):
    try:
        subprocess.run(["git", "-C", root, "add", "-A"], check=True, timeout=10)
        result = subprocess.run(
            ["git", "-C", root, "diff", "--cached", "--quiet"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "-C", root,
                 "-c", "user.name=coresearch",
                 "-c", "user.email=coresearch@local",
                 "commit", "-m", "branching edit"],
                check=True, timeout=10,
            )
    except subprocess.CalledProcessError as e:
        raise HTTPException(400, str(e))
