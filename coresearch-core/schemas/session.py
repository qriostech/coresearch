from pydantic import BaseModel
from datetime import datetime


class Session(BaseModel):
    id: int
    branch_id: int
    runner: str
    attach_command: str
    agent: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
