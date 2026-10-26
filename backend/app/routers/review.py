import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_visible_project, require_role
from app.models import Item, Project, Resolution, Role, User
from app.schemas import (
    ResolutionCreate,
    ResolutionOut,
    ReviewItemOut,
    ReviewLabelOut,
    ReviewQueue,
)
from app.services import audit, review

router = APIRouter(prefix="/projects/{project_id}", tags=["review"])

staff_only = require_role(Role.admin, Role.reviewer)
admin_only = require_role(Role.admin)


@router.get("/review")
def review_queue(
    project: Project = Depends(get_visible_project),
    _: User = Depends(staff_only),
    session: Session = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
) -> ReviewQueue:
    """Unresolved items where labelers disagreed or a flagged labeler took part."""
    items, total = review.review_queue(session, project, limit=limit)
    emails = review.user_emails(session, {lab.user_id for i in items for lab in i.labels})
    return ReviewQueue(
        total=total,
        items=[
            ReviewItemOut(
                id=i.item.id,
                payload=i.item.payload,
                reasons=list(i.reasons),
                labels=[
                    ReviewLabelOut(
                        user_id=lab.user_id,
                        email=emails[lab.user_id],
                        value=lab.value,
                        flagged=lab.flagged,
                    )
                    for lab in i.labels
                ],
            )
            for i in items
        ],
    )


@router.put("/items/{item_id}/resolution")
def resolve_item(
    item_id: int,
    body: ResolutionCreate,
    project: Project = Depends(get_visible_project),
    reviewer: User = Depends(staff_only),
    session: Session = Depends(get_session),
) -> ResolutionOut:
    """Set an item's final label. Replaces an earlier resolution; both are audited."""
    item = session.get(Item, item_id)
    if item is None or item.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if body.value not in project.label_options:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{body.value}' is not a label option for this project",
        )

    resolution = session.exec(select(Resolution).where(Resolution.item_id == item_id)).first()
    before = {"value": resolution.value, "note": resolution.note} if resolution else None
    if resolution is None:
        resolution = Resolution(item_id=item_id, value=body.value)
    resolution.value = body.value
    resolution.note = body.note
    resolution.reviewer_id = reviewer.id
    session.add(resolution)
    audit.record(
        session,
        reviewer,
        "item.resolve",
        "item",
        item_id,
        before=before,
        after={"value": body.value, "note": body.note},
    )
    session.commit()
    return ResolutionOut.model_validate(resolution, from_attributes=True)


@router.get("/export.csv", response_class=StreamingResponse)
def export_final_labels(
    project: Project = Depends(get_visible_project),
    _: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Final labels for every regular item: a reviewer's resolution, else the majority
    of labels given while the labeler was in control. Unresolved items have no label."""
    finals = review.final_labels(session, project)
    payload_fields = sorted({key for f in finals for key in f.item.payload})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["item_id", *payload_fields, "final_label", "source", "labels", "flagged_labels"]
    )
    for f in finals:
        writer.writerow(
            [
                f.item.id,
                *(f.item.payload.get(k, "") for k in payload_fields),
                f.value or "",
                f.source,
                f.labels,
                f.flagged_labels,
            ]
        )
    filename = f"gauge-project-{project.id}-labels.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
