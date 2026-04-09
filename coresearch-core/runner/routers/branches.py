"""Branch lifecycle on the runner: ref resolution, init, soft-delete."""
import os
import shutil
import uuid

from fastapi import APIRouter

from shared.schemas import (
    InitBranchRequest,
    InitBranchResponse,
    ResolveRefRequest,
    ResolveRefResponse,
    SoftDeleteRequest,
)

from runner import log
from runner.config import STORAGE_ROOT
from runner.core.git_ops import (
    checkout_branch,
    clone_local,
    clone_repo,
    resolve_branch_and_commit,
)
from runner.core.tmux import create_tmux_session

router = APIRouter()


@router.post("/resolve-ref", response_model=ResolveRefResponse)
def resolve_ref(body: ResolveRefRequest):
    resolved_branch, resolved_commit = resolve_branch_and_commit(
        body.repository_url, body.branch, body.commit, body.access_token,
    )
    return ResolveRefResponse(branch=resolved_branch, commit=resolved_commit)


@router.post("/init-branch", response_model=InitBranchResponse)
def init_branch(body: InitBranchRequest):
    # Runner decides where to put the branch
    branch_dir = os.path.join(STORAGE_ROOT, "branches", f"{body.name}_{body.uuid[:8]}")
    git_branch = f"coresearch/{body.name}-{body.uuid[:8]}"

    if body.source_branch_path:
        log.info("cloning from local branch", source=body.source_branch_path, dest=branch_dir)
        clone_local(body.source_branch_path, branch_dir)
    else:
        log.info("cloning from remote", repo=body.repository_url, dest=branch_dir)
        clone_repo(body.repository_url, branch_dir, body.source_branch, body.access_token)

    commit = checkout_branch(branch_dir, git_branch, body.source_commit)

    session_uuid = str(uuid.uuid4())
    attach_command = create_tmux_session(session_uuid, working_dir=branch_dir)
    log.info("branch initialized", branch=body.name, git_branch=git_branch, commit=commit[:12], tmux_session=session_uuid)
    sync_command = f"rsync -av {branch_dir}/"

    return InitBranchResponse(
        path=branch_dir,
        commit=commit,
        git_branch=git_branch,
        attach_command=attach_command,
        sync_command=sync_command,
    )


@router.post("/soft-delete", status_code=204)
def soft_delete(body: SoftDeleteRequest):
    if not os.path.isdir(body.path):
        return
    parent = os.path.dirname(body.path)
    fordeletion = os.path.join(parent, ".fordeletion")
    os.makedirs(fordeletion, exist_ok=True)
    dest = os.path.join(fordeletion, os.path.basename(body.path))
    shutil.move(body.path, dest)
    log.info("soft deleted", path=body.path)
