from pydantic import BaseModel
from datetime import datetime


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
