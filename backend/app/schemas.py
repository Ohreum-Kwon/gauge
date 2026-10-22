"""Request and response bodies. Kept apart from the table models so the API can't leak
columns such as password hashes or gold answers by accident."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import Role, TaskType


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role


class UserOut(BaseModel):
    id: int
    email: str
    role: Role
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    task_type: TaskType
    label_options: list[str] = Field(min_length=2, max_length=50)
    gold_rate: float = Field(default=0.1, ge=0, le=1)
    overlap_rate: float = Field(default=0.1, ge=0, le=1)

    @field_validator("label_options")
    @classmethod
    def options_unique_and_nonblank(cls, options: list[str]) -> list[str]:
        cleaned = [o.strip() for o in options]
        if any(not o for o in cleaned):
            raise ValueError("label options can't be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("label options must be unique")
        return cleaned


class ProjectOut(BaseModel):
    id: int
    name: str
    task_type: TaskType
    label_options: list[str]
    gold_rate: float
    overlap_rate: float
    created_at: datetime


class ProjectSummary(ProjectOut):
    item_count: int
    gold_item_count: int
    label_count: int


class MembersUpdate(BaseModel):
    user_ids: list[int]


class UploadResult(BaseModel):
    created: int
    gold: int


class ItemOut(BaseModel):
    """An item as admins see it, gold answer included."""

    id: int
    payload: dict[str, Any]
    gold_answer: str | None
    label_count: int


class TaskItem(BaseModel):
    """An item as labelers see it. No gold answer, so gold items look like any other."""

    id: int
    payload: dict[str, Any]


class Task(BaseModel):
    assignment_id: int
    project_id: int
    task_type: TaskType
    label_options: list[str]
    item: TaskItem


class LabelCreate(BaseModel):
    value: str = Field(min_length=1, max_length=200)
    # Capped at an hour: anything longer is a tab left open, not time spent labeling.
    time_spent_ms: int = Field(ge=0, le=60 * 60 * 1000)


class LabelOut(BaseModel):
    id: int
    item_id: int
    assignment_id: int
    value: str
    time_spent_ms: int
    created_at: datetime


class Progress(BaseModel):
    completed: int
    remaining: int
