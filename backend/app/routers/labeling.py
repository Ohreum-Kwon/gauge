from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, exists, func, select

from app.db import get_session
from app.deps import get_visible_project, require_role
from app.models import (
    Assignment,
    AssignmentStatus,
    Item,
    Label,
    Project,
    Role,
    User,
    utcnow,
)
from app.schemas import LabelCreate, LabelOut, Progress, Task, TaskItem
from app.services import audit
from app.services.queue import get_or_assign_next

router = APIRouter(tags=["labeling"])

labeler_only = require_role(Role.labeler)


@router.get(
    "/projects/{project_id}/queue/next",
    response_model=Task,
    responses={204: {"description": "Nothing left to label"}},
)
def next_task(
    project: Project = Depends(get_visible_project),
    user: User = Depends(labeler_only),
    session: Session = Depends(get_session),
) -> Task | Response:
    assignment = get_or_assign_next(session, project, user)
    if assignment is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    item = session.get(Item, assignment.item_id)
    return Task(
        assignment_id=assignment.id,
        project_id=project.id,
        task_type=project.task_type,
        label_options=project.label_options,
        item=TaskItem(id=item.id, payload=item.payload),
    )


@router.get("/projects/{project_id}/queue/progress")
def progress(
    project: Project = Depends(get_visible_project),
    user: User = Depends(labeler_only),
    session: Session = Depends(get_session),
) -> Progress:
    completed = session.exec(
        select(func.count())
        .select_from(Label)
        .join(Item)
        .where(Item.project_id == project.id, Label.user_id == user.id)
    ).one()
    unassigned = session.exec(
        select(func.count()).where(
            Item.project_id == project.id, ~exists().where(Assignment.item_id == Item.id)
        )
    ).one()
    pending = session.exec(
        select(func.count())
        .select_from(Assignment)
        .join(Item)
        .where(
            Item.project_id == project.id,
            Assignment.user_id == user.id,
            Assignment.status == AssignmentStatus.pending,
        )
    ).one()
    return Progress(completed=completed, remaining=unassigned + pending)


@router.post("/assignments/{assignment_id}/label", status_code=status.HTTP_201_CREATED)
def submit_label(
    assignment_id: int,
    body: LabelCreate,
    user: User = Depends(labeler_only),
    session: Session = Depends(get_session),
) -> LabelOut:
    assignment = session.get(Assignment, assignment_id, with_for_update=True)
    if assignment is None or assignment.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if assignment.status != AssignmentStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item is already labeled")

    item = session.get(Item, assignment.item_id)
    project = session.get(Project, item.project_id)
    if body.value not in project.label_options:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{body.value}' is not a label option for this project",
        )

    label = Label(
        item_id=item.id,
        user_id=user.id,
        assignment_id=assignment.id,
        value=body.value,
        time_spent_ms=body.time_spent_ms,
    )
    assignment.status = AssignmentStatus.completed
    assignment.completed_at = utcnow()
    session.add_all([label, assignment])
    session.flush()
    audit.record(
        session,
        user,
        "label.create",
        "label",
        label.id,
        after={"item_id": item.id, "value": body.value, "time_spent_ms": body.time_spent_ms},
    )
    session.commit()
    return LabelOut.model_validate(label, from_attributes=True)
