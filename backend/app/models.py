"""Database tables.

The schema is migrated by Alembic (see alembic/versions). Any change here needs a new
migration: `uv run alembic revision --autogenerate -m "..."`.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# JSONB on Postgres (indexable, compact); plain JSON elsewhere.
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def created_at_field() -> Any:
    return Field(
        default_factory=utcnow,
        sa_column_kwargs={"nullable": False},
        sa_type=DateTime(timezone=True),
    )


class Role(StrEnum):
    admin = "admin"
    labeler = "labeler"
    reviewer = "reviewer"


class TaskType(StrEnum):
    image_classification = "image_classification"
    pairwise_preference = "pairwise_preference"


class AssignmentStatus(StrEnum):
    pending = "pending"
    completed = "completed"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    password_hash: str
    role: Role
    created_at: datetime = created_at_field()


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    task_type: TaskType
    label_options: list[str] = Field(sa_column=Column(JsonType, nullable=False))
    # Share of each labeler's queue drawn from gold items (known answers).
    gold_rate: float = Field(default=0.1, ge=0, le=1)
    # Share of items that get labeled by more than one person, for agreement stats.
    overlap_rate: float = Field(default=0.1, ge=0, le=1)
    # How many labelers each overlap item goes to.
    overlap_labelers: int = Field(default=3, sa_column_kwargs={"server_default": "3"})
    # The acceptable gold error rate: the center line of each labeler's control chart.
    target_error_rate: float = Field(default=0.1, sa_column_kwargs={"server_default": "0.1"})
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = created_at_field()


class ProjectMember(SQLModel, table=True):
    """A labeler or reviewer assigned to a project."""

    __tablename__ = "project_members"

    project_id: int = Field(foreign_key="projects.id", primary_key=True, ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", primary_key=True, ondelete="CASCADE")


class Item(SQLModel, table=True):
    __tablename__ = "items"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True, ondelete="CASCADE")
    # Shape depends on the task type, e.g. {"image_url": ...} for image classification.
    payload: dict[str, Any] = Field(sa_column=Column(JsonType, nullable=False))
    # Set only for gold items. Never sent to labelers. Every labeler may see each gold item.
    gold_answer: str | None = None
    # How many labelers a regular item goes to: 1, or project.overlap_labelers for overlap items.
    required_labels: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    created_at: datetime = created_at_field()


class Assignment(SQLModel, table=True):
    __tablename__ = "assignments"
    __table_args__ = (Index("ix_assignments_user_status", "user_id", "status"),)

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="items.id", index=True, ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE")
    status: AssignmentStatus = AssignmentStatus.pending
    created_at: datetime = created_at_field()
    completed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class Label(SQLModel, table=True):
    __tablename__ = "labels"

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="items.id", index=True, ondelete="CASCADE")
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    assignment_id: int = Field(foreign_key="assignments.id", unique=True, ondelete="CASCADE")
    value: str = Field(max_length=200)
    time_spent_ms: int = Field(ge=0)
    created_at: datetime = created_at_field()


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    # Null for actions the system takes on its own.
    actor_id: int | None = Field(default=None, foreign_key="users.id", ondelete="SET NULL")
    action: str = Field(max_length=100, index=True)
    target_type: str = Field(max_length=50)
    target_id: int | None = None
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JsonType))
    created_at: datetime = created_at_field()
