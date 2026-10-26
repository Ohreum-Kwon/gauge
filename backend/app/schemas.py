"""Request and response bodies. Kept apart from the table models so the API can't leak
columns such as password hashes or gold answers by accident."""

from datetime import date, datetime
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
    overlap_labelers: int = Field(default=3, ge=2, le=20)
    target_error_rate: float = Field(default=0.1, gt=0, lt=1)

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
    overlap_labelers: int
    target_error_rate: float
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


class GoldAccuracy(BaseModel):
    gold_answered: int
    gold_correct: int
    accuracy: float | None


class AlertOut(BaseModel):
    day: date
    rule: str
    description: str
    # True when the labeler is worse than target; False flags unusually good work.
    above: bool


class ChartPointOut(BaseModel):
    day: date
    gold_answered: int
    errors: int
    error_rate: float
    ucl: float
    lcl: float


class ControlChart(BaseModel):
    user_id: int
    center: float
    points: list[ChartPointOut]
    alerts: list[AlertOut]


class LabelerQualityOut(BaseModel):
    user_id: int
    email: str
    labels: int
    gold_answered: int
    gold_correct: int
    accuracy: float | None
    median_time_ms: int | None
    # Share of labels submitted in under a second.
    fast_share: float | None
    status: str
    latest_alert: AlertOut | None


class PairAgreementOut(BaseModel):
    user_a: int
    user_b: int
    kappa: float | None
    shared_items: int


class AgreementOut(BaseModel):
    fleiss_kappa: float | None
    overlap_items: int
    raters_per_item: int
    pairs: list[PairAgreementOut]


class ProjectQuality(BaseModel):
    target_error_rate: float
    labelers: list[LabelerQualityOut]
    agreement: AgreementOut


class ReviewLabelOut(BaseModel):
    user_id: int
    email: str
    value: str
    flagged: bool


class ReviewItemOut(BaseModel):
    id: int
    payload: dict[str, Any]
    reasons: list[str]
    labels: list[ReviewLabelOut]


class ReviewQueue(BaseModel):
    total: int
    items: list[ReviewItemOut]


class ResolutionCreate(BaseModel):
    value: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class ResolutionOut(BaseModel):
    item_id: int
    value: str
    reviewer_id: int | None
    note: str | None
    created_at: datetime


class AuditEntryOut(BaseModel):
    id: int
    actor_email: str | None
    action: str
    target_type: str
    target_id: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class AuditPage(BaseModel):
    total: int
    entries: list[AuditEntryOut]
