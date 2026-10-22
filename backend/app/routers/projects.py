from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlmodel import Session, col, func, select

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user, get_visible_project, require_role
from app.models import Item, Label, Project, ProjectMember, Role, User
from app.schemas import (
    ItemOut,
    MembersUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectSummary,
    UploadResult,
    UserOut,
)
from app.services import audit
from app.services.ingest import IngestError, parse_items

router = APIRouter(prefix="/projects", tags=["projects"])

admin_only = require_role(Role.admin)


@router.get("")
def list_projects(
    user: User = Depends(get_current_user), session: Session = Depends(get_session)
) -> list[ProjectOut]:
    query = select(Project).order_by(col(Project.id))
    if user.role != Role.admin:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return [ProjectOut.model_validate(p, from_attributes=True) for p in session.exec(query)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    admin: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> ProjectOut:
    project = Project(**body.model_dump(), created_by=admin.id)
    session.add(project)
    session.flush()
    audit.record(session, admin, "project.create", "project", project.id, after=body.model_dump())
    session.commit()
    return ProjectOut.model_validate(project, from_attributes=True)


@router.get("/{project_id}")
def get_project(
    project: Project = Depends(get_visible_project), session: Session = Depends(get_session)
) -> ProjectSummary:
    item_count, gold_count = session.exec(
        select(func.count(), func.count(Item.gold_answer)).where(Item.project_id == project.id)
    ).one()
    label_count = session.exec(
        select(func.count()).select_from(Label).join(Item).where(Item.project_id == project.id)
    ).one()
    return ProjectSummary(
        **ProjectOut.model_validate(project, from_attributes=True).model_dump(),
        item_count=item_count,
        gold_item_count=gold_count,
        label_count=label_count,
    )


@router.get("/{project_id}/members")
def list_members(
    project: Project = Depends(get_visible_project),
    _: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> list[UserOut]:
    users = session.exec(
        select(User)
        .join(ProjectMember)
        .where(ProjectMember.project_id == project.id)
        .order_by(col(User.id))
    )
    return [UserOut.model_validate(u, from_attributes=True) for u in users]


@router.put("/{project_id}/members")
def set_members(
    body: MembersUpdate,
    project: Project = Depends(get_visible_project),
    admin: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> list[UserOut]:
    """Replace the project's labelers and reviewers with the given users."""
    wanted = set(body.user_ids)
    users = session.exec(select(User).where(col(User.id).in_(wanted))).all() if wanted else []
    if len(users) != len(wanted):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown user id")
    if any(u.role == Role.admin for u in users):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only labelers and reviewers can be members"
        )

    current = set(
        session.exec(
            select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
        ).all()
    )
    for user_id in current - wanted:
        session.delete(session.get(ProjectMember, (project.id, user_id)))
    for user_id in wanted - current:
        session.add(ProjectMember(project_id=project.id, user_id=user_id))
    audit.record(
        session,
        admin,
        "project.members.update",
        "project",
        project.id,
        before={"user_ids": sorted(current)},
        after={"user_ids": sorted(wanted)},
    )
    session.commit()
    return [UserOut.model_validate(u, from_attributes=True) for u in sorted(users, key=_by_id)]


@router.post("/{project_id}/items", status_code=status.HTTP_201_CREATED)
async def upload_items(
    file: UploadFile,
    project: Project = Depends(get_visible_project),
    admin: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> UploadResult:
    """Add items from a CSV or JSON file. Rows with a gold_answer become gold items."""
    max_bytes = get_settings().max_upload_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {max_bytes} bytes"
        )
    try:
        parsed = parse_items(file.filename or "", content, project.task_type, project.label_options)
    except IngestError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    session.add_all(
        Item(project_id=project.id, payload=p.payload, gold_answer=p.gold_answer) for p in parsed
    )
    gold = sum(p.gold_answer is not None for p in parsed)
    audit.record(
        session,
        admin,
        "items.upload",
        "project",
        project.id,
        after={"filename": file.filename, "created": len(parsed), "gold": gold},
    )
    session.commit()
    return UploadResult(created=len(parsed), gold=gold)


@router.get("/{project_id}/items")
def list_items(
    project: Project = Depends(get_visible_project),
    _: User = Depends(admin_only),
    session: Session = Depends(get_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[ItemOut]:
    label_count = (
        select(func.count()).where(Label.item_id == Item.id).correlate(Item).scalar_subquery()
    )
    rows = session.exec(
        select(Item, label_count)
        .where(Item.project_id == project.id)
        .order_by(col(Item.id))
        .offset(offset)
        .limit(limit)
    )
    return [
        ItemOut(id=item.id, payload=item.payload, gold_answer=item.gold_answer, label_count=n)
        for item, n in rows
    ]


def _by_id(user: User) -> int:
    return user.id or 0
