from pydantic import BaseModel
from datetime import datetime

from schemas.session import Session


class Branch(BaseModel):
    id: int
    uuid: str
    seed_id: int
    name: str
    description: str
    path: str
    sync_command: str
    commit: str
    git_branch: str
    created_at: datetime
    parent_branch_id: int | None = None
    parent_iteration_hash: str | None = None
    session: Session | None = None
