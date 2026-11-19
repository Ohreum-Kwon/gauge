from fastapi import APIRouter, Depends, status
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import get_visible_project, require_role
from app.models import EventKind, Project, ProjectEvent, Role, User, utcnow
from app.schemas import EventCreate, EventOut
from app.services import audit

router = APIRouter(prefix="/projects/{project_id}/events", tags=["events"])


@router.get("")
def list_events(
    project: Project = Depends(get_visible_project),
    _: User = Depends(require_role(Role.admin, Role.reviewer)),
    session: Session = Depends(get_session),
) -> list[EventOut]:
    """Changes root-cause analysis checks against: guideline edits, model updates and
    batch uploads, oldest first."""
    events = session.exec(
        select(ProjectEvent)
        .where(ProjectEvent.project_id == project.id)
        .order_by(col(ProjectEvent.occurred_at), col(ProjectEvent.id))
    )
    return [EventOut.model_validate(e, from_attributes=True) for e in events]


@router.post("", status_code=status.HTTP_201_CREATED)
def log_guideline_change(
    body: EventCreate,
    project: Project = Depends(get_visible_project),
    admin: User = Depends(require_role(Role.admin)),
    session: Session = Depends(get_session),
) -> EventOut:
    """Record a change to the labeling guidelines, so a shift that starts right after it
    can be traced back to it."""
    event = ProjectEvent(
        project_id=project.id,
        kind=EventKind.guideline_change,
        description=body.description,
        occurred_at=body.occurred_at or utcnow(),
    )
    session.add(event)
    session.flush()
    audit.record(
        session,
        admin,
        "event.create",
        "project",
        project.id,
        after={"kind": event.kind.value, "description": event.description},
    )
    session.commit()
    return EventOut.model_validate(event, from_attributes=True)
