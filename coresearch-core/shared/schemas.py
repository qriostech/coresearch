"""Centralized Pydantic models shared by controlplane and runner.

Both services import from here. The runner-facing models (RunnerWriteFileRequest,
ResolveRefRequest, InitBranchRequest, ...) describe the runner's HTTP wire format
— the controlplane uses them to type its calls to the runner, and the runner
declares its endpoints with the same types. This guarantees the two services
cannot drift on the request/response shapes they exchange.
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# User-facing controlplane request bodies
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    user_id: int = 1
    llm_provider: str = "default_llm"
    llm_model: str = "default_model"


class CreateSeedRequest(BaseModel):
    name: str
    repository_url: str
    branch: str | None = None
    commit: str | None = None
    access_token: str | None = None


class SeedFromIterationRequest(BaseModel):
    name: str
    branch_id: int
    iteration_hash: str


class CreateBranchRequest(BaseModel):
    name: str
    description: str = ""
    kind: str = "tmux"          # session multiplexer kind (was: runner)
    agent: str = "default"
    runner_id: int | None = None  # which runner host to schedule on


class UpdateBranchRequest(BaseModel):
    description: str


class ForkBranchRequest(BaseModel):
    name: str
    description: str = ""
    iteration_hash: str
    agent: str = "default"


class WriteFileRequest(BaseModel):
    """User-facing workdir write (controlplane PUT /branches/{id}/workdir/file)."""
    path: str
    content: str


class AddCommentRequest(BaseModel):
    body: str
    user_id: int = 1


class UpdateIterationRequest(BaseModel):
    description: str | None = None


class RenameRunnerRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Runner-facing wire schemas (controlplane → runner over HTTP)
# ---------------------------------------------------------------------------

class ResolveRefRequest(BaseModel):
    repository_url: str
    branch: str | None = None
    commit: str | None = None
    access_token: str | None = None


class ResolveRefResponse(BaseModel):
    branch: str
    commit: str


class InitBranchRequest(BaseModel):
    name: str
    uuid: str
    repository_url: str
    source_branch: str
    source_commit: str
    access_token: str | None = None
    source_branch_path: str | None = None  # for forking from existing branch


class InitBranchResponse(BaseModel):
    path: str
    commit: str
    git_branch: str
    attach_command: str
    sync_command: str


class SoftDeleteRequest(BaseModel):
    path: str


class CreateSessionRequest(BaseModel):
    working_dir: str


class CreateSessionResponse(BaseModel):
    attach_command: str


class SessionAliveResponse(BaseModel):
    alive: bool


class PushRequest(BaseModel):
    repo_path: str
    url: str
    refspec: str
    access_token: str | None = None


class RunnerWriteFileRequest(BaseModel):
    """Runner-side workdir write (runner PUT /workdir/file). Includes ``root`` so
    the runner knows which branch directory the path is relative to."""
    root: str
    path: str
    content: str


# ---------------------------------------------------------------------------
# Internal API (runner daemon → controlplane)
# ---------------------------------------------------------------------------

class RegisterRunnerRequest(BaseModel):
    name: str
    url: str
    capabilities: dict = {}


class InternalIterationRequest(BaseModel):
    branch_id: int
    hash: str


class InternalMetricsRequest(BaseModel):
    branch_id: int
    hash: str
    metrics: dict[str, float]


class InternalVisualRequest(BaseModel):
    branch_id: int
    hash: str
    filename: str
    format: str
    path: str


class InternalDocRequest(BaseModel):
    branch_id: int
    hash: str
    field: Literal["hypothesis", "analysis", "guidelines_version"]
    content: str


class InternalSessionStatusRequest(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# User-facing controlplane response models
# ---------------------------------------------------------------------------

class Project(BaseModel):
    id: int
    name: str
    uuid: str
    user_id: int
    created_at: datetime
    updated_at: datetime
    llm_provider: str
    llm_model: str
    project_root: str


class Seed(BaseModel):
    id: int
    uuid: str
    project_id: int
    name: str
    repository_url: str
    branch: str
    commit: str
    created_at: datetime


class Runner(BaseModel):
    id: int
    name: str
    url: str
    status: str
    capabilities: dict[str, Any]
    registered_at: datetime
    last_heartbeat: datetime | None


class Session(BaseModel):
    id: int
    branch_id: int
    kind: str  # session multiplexer kind, e.g. "tmux" (was: runner — collided with branches.runner_id naming)
    attach_command: str
    agent: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class Branch(BaseModel):
    id: int
    uuid: str
    seed_id: int
    runner_id: int | None
    name: str
    description: str
    path: str
    sync_command: str
    commit: str
    git_branch: str
    created_at: datetime
    parent_branch_id: int | None = None
    # parent_iteration_id is the FK; parent_iteration_hash is denormalized via
    # LEFT JOIN to iterations for convenience (the frontend keys layout nodes
    # by hash). Both default to None for non-fork branches.
    parent_iteration_id: int | None = None
    parent_iteration_hash: str | None = None
    session: Session | None = None


class IterationMetric(BaseModel):
    id: int
    iteration_id: int
    key: str
    value: float
    recorded_at: datetime


class IterationVisual(BaseModel):
    id: int
    iteration_id: int
    filename: str
    format: str
    path: str
    created_at: datetime


class IterationComment(BaseModel):
    id: int
    iteration_id: int
    user_id: int
    user_name: str
    body: str
    created_at: datetime


class Iteration(BaseModel):
    id: int
    branch_id: int
    hash: str
    name: str
    description: str | None
    hypothesis: str | None
    analysis: str | None
    guidelines_version: str | None
    created_at: datetime
    metrics: list[IterationMetric]
    visuals: list[IterationVisual]
    comments: list[IterationComment]


class PushResponse(BaseModel):
    message: str


class CommentCreatedResponse(BaseModel):
    id: int
