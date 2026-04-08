from pydantic import BaseModel
from datetime import datetime
from typing import Optional


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
    description: Optional[str]
    created_at: datetime
    metrics: list[IterationMetric] = []
    visuals: list[IterationVisual] = []
    comments: list[IterationComment] = []
