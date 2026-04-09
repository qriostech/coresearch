"""Git operations: push, diff, tree, file."""
import subprocess

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from shared.schemas import PushRequest

from runner.core.git_ops import git_diff, git_push, git_show_file, git_tree

router = APIRouter()


@router.post("/git/push")
def push(body: PushRequest):
    try:
        msg = git_push(body.repo_path, body.url, body.refspec, body.access_token)
        return {"message": msg}
    except subprocess.CalledProcessError as e:
        raise HTTPException(400, e.stderr.strip() or str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "push timed out")


@router.get("/git/diff")
def get_diff(repo_path: str = Query(...), from_hash: str = Query(...), to_hash: str = Query(...)):
    try:
        return PlainTextResponse(git_diff(repo_path, from_hash, to_hash))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "diff timed out")


@router.get("/git/tree")
def get_tree(repo_path: str = Query(...), hash: str = Query(...)):
    try:
        return git_tree(repo_path, hash)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "timed out")


@router.get("/git/file")
def get_file(repo_path: str = Query(...), hash: str = Query(...), path: str = Query(...)):
    try:
        return PlainTextResponse(git_show_file(repo_path, hash, path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "timed out")
