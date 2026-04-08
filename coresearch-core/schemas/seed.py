from pydantic import BaseModel
from datetime import datetime


class Seed(BaseModel):
    id: int
    uuid: str
    project_id: int
    name: str
    repository_url: str
    path: str
    branch: str
    commit: str
    has_access_token: bool
    created_at: datetime
