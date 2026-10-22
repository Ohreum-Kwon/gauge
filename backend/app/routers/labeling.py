import random

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, func, select

from app.db import get_session
from app.deps import get_rng, get_visible_project, require_role
from app.models import (
    Assignment,
    AssignmentStatus,
    Item,
    Label,
    Project,
    Role,
    User,
)
from app.schemas import GoldAccuracy, LabelCreate, LabelOut, Progress, Task, TaskItem
from app.services import quality
from app.services.labeling import submit_label
from app.services.queue import get_or_assign_next, remaining_regular_items

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
    rng: random.Random = Depends(get_rng),
) -> Task | Response:
    assignment = get_or_assign_next(session, project, user, rng)
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
    """Labels done and regular items left. Gold items are mixed in on top, so the total
    a labeler ends up doing is a little higher than completed + remaining."""
    completed = session.exec(
        select(func.count())
        .select_from(Label)
        .join(Item)
        .where(Item.project_id == project.id, Label.user_id == user.id)
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
    return Progress(
        completed=completed, remaining=remaining_regular_items(session, project, user) + pending
    )


@router.get("/projects/{project_id}/queue/accuracy")
def my_accuracy(
    project: Project = Depends(get_visible_project),
    user: User = Depends(labeler_only),
    session: Session = Depends(get_session),
) -> GoldAccuracy:
    """The labeler's own accuracy on gold items so far. Only totals, so it can't reveal
    which items were gold."""
    gold = [r for r in quality.load_rows(session, project, user_id=user.id) if r.is_gold]
    correct = sum(not r.is_error for r in gold)
    return GoldAccuracy(
        gold_answered=len(gold),
        gold_correct=correct,
        accuracy=correct / len(gold) if gold else None,
    )


@router.post("/assignments/{assignment_id}/label", status_code=status.HTTP_201_CREATED)
def create_label(
    assignment_id: int,
    body: LabelCreate,
    user: User = Depends(labeler_only),
    session: Session = Depends(get_session),
) -> LabelOut:
    assignment = session.get(Assignment, assignment_id, with_for_update=True)
    if assignment is None or assignment.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    label = submit_label(session, assignment, user, body.value, body.time_spent_ms)
    return LabelOut.model_validate(label, from_attributes=True)
