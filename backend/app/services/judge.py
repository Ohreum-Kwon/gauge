"""Run a model labeler (an LLM judge) in shadow mode alongside the people.

The judge labels the items people have labeled, after them. Its labels are charted with
the same p-chart as everyone's, plus a second chart of how often it disagrees with the
people who are in control, so a model update that quietly shifts its answers shows up
even on items with no gold answer. Shadow labels never take a person's place in the
queue, never count toward agreement among people, and never decide a final label.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlmodel import Session, col, exists, func, select

from app.judges import Judge
from app.models import (
    Assignment,
    AssignmentStatus,
    EventKind,
    Item,
    Label,
    Project,
    ProjectEvent,
    ProjectMember,
    Role,
    User,
    utcnow,
)
from app.security import NO_PASSWORD
from app.services import audit

# How long after the first person's label the judge's label is stamped, when backdating.
SHADOW_DELAY = timedelta(seconds=30)


def get_or_create_judge(session: Session, project: Project, email: str) -> User:
    """The model labeler account, added to the project if it isn't a member yet."""
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, password_hash=NO_PASSWORD, role=Role.labeler, is_model=True)
        session.add(user)
        session.flush()
    elif not user.is_model:
        raise ValueError(f"{email} is a person's account, not a model labeler")
    if session.get(ProjectMember, (project.id, user.id)) is None:
        session.add(ProjectMember(project_id=project.id, user_id=user.id))
        session.flush()
    return user


def items_to_judge(
    session: Session, project: Project, judge: User, limit: int | None = None
) -> list[tuple[Item, datetime]]:
    """Items a person has labeled and the judge hasn't, with the first person's label
    time, oldest first."""
    first_label = (
        select(Label.item_id, func.min(Label.created_at).label("at"))
        .join(User, col(User.id) == Label.user_id)
        .where(col(User.is_model).is_(False))
        .group_by(col(Label.item_id))
        .subquery()
    )
    query = (
        select(Item, first_label.c.at)
        .join(first_label, first_label.c.item_id == Item.id)
        .where(
            Item.project_id == project.id,
            ~exists().where(Assignment.item_id == Item.id, Assignment.user_id == judge.id),
        )
        .order_by(first_label.c.at, col(Item.id))
    )
    if limit is not None:
        query = query.limit(limit)
    return [(item, at) for item, at in session.exec(query)]


def run_judge(
    session: Session,
    project: Project,
    user: User,
    judge: Judge,
    items: Iterable[tuple[Item, datetime]],
    backdate: bool = False,
) -> int:
    """Label `items` with `judge` as `user`. Commits once at the end.

    With `backdate`, each label is stamped just after the first person's label on that
    item (the simulation uses this); otherwise it is stamped now. When the judge's version
    differs from the one on its previous label, a model_update event is recorded at the
    first label of the new version.
    """
    previous = session.exec(
        select(Label.model_version)
        .where(Label.user_id == user.id, Item.project_id == project.id)
        .join(Item)
        .order_by(col(Label.created_at).desc())
        .limit(1)
    ).first()

    count = 0
    first_at: datetime | None = None
    for item, first_label_at in items:
        at = first_label_at + SHADOW_DELAY if backdate else utcnow()
        value = judge.label(item.payload, project.label_options)
        assignment = Assignment(
            item_id=item.id, user_id=user.id, status=AssignmentStatus.completed, completed_at=at
        )
        session.add(assignment)
        session.flush()
        session.add(
            Label(
                item_id=item.id,
                user_id=user.id,
                assignment_id=assignment.id,
                value=value,
                time_spent_ms=0,
                model_version=judge.version,
                created_at=at,
            )
        )
        first_at = first_at or at
        count += 1

    if count and previous is not None and previous != judge.version:
        session.add(
            ProjectEvent(
                project_id=project.id,
                kind=EventKind.model_update,
                description=f"{user.email} updated from {previous} to {judge.version}",
                user_id=user.id,
                occurred_at=first_at,
            )
        )
    if count:
        audit.record(
            session,
            None,
            "judge.run",
            "project",
            project.id,
            after={"judge": user.email, "version": judge.version, "labels": count},
        )
    session.commit()
    return count
