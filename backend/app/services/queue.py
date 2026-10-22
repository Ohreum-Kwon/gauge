"""Decide which item a labeler sees next.

Each request draws a gold item (known answer) with probability gold_rate, otherwise a
regular item. Labelers can't tell the two apart, which is what makes gold accuracy an
honest measurement. Every labeler may see each gold item once; regular items go to
`required_labels` labelers (1, or the project's overlap_labelers for overlap items).
"""

import random

from sqlmodel import Session, col, exists, func, select

from app.models import Assignment, AssignmentStatus, Item, Project, User


def get_or_assign_next(
    session: Session, project: Project, user: User, rng: random.Random | None = None
) -> Assignment | None:
    """Return the user's open assignment in this project, or assign them a new item.

    Returns None when no regular work is left (gold items alone don't keep a queue going).
    Commits a new assignment.
    """
    pending = session.exec(
        select(Assignment)
        .join(Item)
        .where(
            Item.project_id == project.id,
            Assignment.user_id == user.id,
            Assignment.status == AssignmentStatus.pending,
        )
        .order_by(col(Assignment.id))
        .limit(1)
    ).first()
    if pending is not None:
        return pending

    # Pick (and lock) a regular item first: when none is left the queue is done, even
    # if unseen gold items remain, since gold alone measures but doesn't get work done.
    item = _next_regular_item(session, project, user)
    if item is None:
        return None
    rng = rng or random
    if project.gold_rate > 0 and rng.random() < project.gold_rate:
        item = _next_gold_item(session, project, user) or item

    assignment = Assignment(item_id=item.id, user_id=user.id)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def remaining_regular_items(session: Session, project: Project, user: User) -> int:
    """Regular items this user could still be given."""
    return session.exec(
        select(func.count()).select_from(_regular_candidates(project, user).subquery())
    ).one()


def _not_seen_by(user: User):
    return ~exists().where(Assignment.item_id == Item.id, Assignment.user_id == user.id)


def _assignment_count():
    return (
        select(func.count()).where(Assignment.item_id == Item.id).correlate(Item).scalar_subquery()
    )


def _regular_candidates(project: Project, user: User):
    return select(Item).where(
        Item.project_id == project.id,
        col(Item.gold_answer).is_(None),
        _not_seen_by(user),
        _assignment_count() < Item.required_labels,
    )


def _next_regular_item(session: Session, project: Project, user: User) -> Item | None:
    # Finish overlap items other labelers have started before opening new ones, so
    # agreement data builds up early instead of trickling in at the end. Lock the chosen
    # row and skip rows other labelers have locked, so two people asking at the same
    # moment can't push an item past its required labels.
    query = (
        _regular_candidates(project, user)
        .order_by(_assignment_count().desc(), col(Item.id))
        .with_for_update(skip_locked=True, of=Item)
    )
    return session.exec(query.limit(1)).first()


def _next_gold_item(session: Session, project: Project, user: User) -> Item | None:
    # Random order, so labelers don't all meet the same gold items in the same sequence.
    return session.exec(
        select(Item)
        .where(
            Item.project_id == project.id,
            col(Item.gold_answer).is_not(None),
            _not_seen_by(user),
        )
        .order_by(func.random())
        .limit(1)
    ).first()
