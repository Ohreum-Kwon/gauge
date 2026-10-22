"""Decide which item a labeler sees next.

For now every item is labeled once, in upload order. Mixing in gold items at the
project's gold_rate and sending a share of items to several labelers (overlap_rate)
come next, and both slot in here.
"""

from sqlmodel import Session, col, exists, select

from app.models import Assignment, AssignmentStatus, Item, Project, User


def get_or_assign_next(session: Session, project: Project, user: User) -> Assignment | None:
    """Return the user's open assignment in this project, or assign them a new item.

    Returns None when there's nothing left to label. Commits a new assignment.
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

    # Lock the chosen item row and skip rows other labelers have locked, so two people
    # asking at the same moment don't both get the same item.
    item = session.exec(
        select(Item)
        .where(
            Item.project_id == project.id,
            ~exists().where(Assignment.item_id == Item.id),
        )
        .order_by(col(Item.id))
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if item is None:
        return None

    assignment = Assignment(item_id=item.id, user_id=user.id)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment
