from datetime import datetime

from fastapi import HTTPException, status
from sqlmodel import Session

from app.models import Assignment, AssignmentStatus, Item, Label, Project, User, utcnow
from app.services import audit


def submit_label(
    session: Session,
    assignment: Assignment,
    user: User,
    value: str,
    time_spent_ms: int,
    at: datetime | None = None,
) -> Label:
    """Record a label for an open assignment and close it. Commits.

    `at` backdates the label; only the labeler simulation uses it.
    """
    if assignment.status != AssignmentStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item is already labeled")
    item = session.get(Item, assignment.item_id)
    project = session.get(Project, item.project_id)
    if value not in project.label_options:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{value}' is not a label option for this project",
        )

    at = at or utcnow()
    label = Label(
        item_id=item.id,
        user_id=user.id,
        assignment_id=assignment.id,
        value=value,
        time_spent_ms=time_spent_ms,
        created_at=at,
    )
    assignment.status = AssignmentStatus.completed
    assignment.completed_at = at
    session.add_all([label, assignment])
    session.flush()
    audit.record(
        session,
        user,
        "label.create",
        "label",
        label.id,
        after={"item_id": item.id, "value": value, "time_spent_ms": time_spent_ms},
    )
    session.commit()
    return label
