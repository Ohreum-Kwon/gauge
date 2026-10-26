"""What reviewers look at, and the final labels a project hands to the dataset.

A label is trusted unless its labeler's control chart was out of control (worse than
target) on the day they gave it. An item's final label is a reviewer's resolution if
there is one, else the majority of its trusted labels. Items with no such majority (a
tie, or only untrusted labels) go to the review queue; items whose trusted labels settle
it don't, even if an untrusted label disagreed.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlmodel import Session, col, select

from app.models import Item, Project, Resolution, User
from app.services.quality import LabelRow, labeler_chart, load_rows


class Reason(StrEnum):
    disagreement = "disagreement"
    flagged_labeler = "flagged_labeler"


@dataclass(frozen=True)
class ReviewLabel:
    user_id: int
    value: str
    # True when the label was given on a day the labeler was out of control.
    flagged: bool


@dataclass(frozen=True)
class ReviewItem:
    item: Item
    reasons: list[Reason]
    labels: list[ReviewLabel]


@dataclass(frozen=True)
class FinalLabel:
    item: Item
    value: str | None
    source: str  # "resolution", "majority" or "unresolved"
    labels: int
    flagged_labels: int


def flagged_days(project: Project, rows: list[LabelRow]) -> dict[int, set[date]]:
    """For each labeler, the days their p-chart raised an upward (worse-than-target) alert."""
    by_user: dict[int, list[LabelRow]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    return {
        user_id: {a.day for a in labeler_chart(project, user_rows).alerts if a.violation.above}
        for user_id, user_rows in by_user.items()
    }


def _regular_labels(project: Project, rows: list[LabelRow]) -> dict[int, list[ReviewLabel]]:
    flagged = flagged_days(project, rows)
    labels: dict[int, list[ReviewLabel]] = defaultdict(list)
    for row in rows:
        if not row.is_gold:
            is_flagged = row.created_at.date() in flagged.get(row.user_id, set())
            labels[row.item_id].append(ReviewLabel(row.user_id, row.value, is_flagged))
    return labels


def _majority(labels: list[ReviewLabel]) -> str | None:
    """The most common value among unflagged labels; None on a tie or when none are left."""
    counts = Counter(label.value for label in labels if not label.flagged).most_common(2)
    if not counts or (len(counts) == 2 and counts[0][1] == counts[1][1]):
        return None
    return counts[0][0]


def _review_reasons(labels: list[ReviewLabel]) -> list[Reason]:
    """Why an item needs a reviewer; empty when its trusted labels already settle it."""
    if _majority(labels) is not None:
        return []
    reasons = []
    if len({label.value for label in labels}) > 1:
        reasons.append(Reason.disagreement)
    if any(label.flagged for label in labels):
        reasons.append(Reason.flagged_labeler)
    return reasons


def _resolved_item_ids(session: Session, project: Project) -> set[int]:
    return set(
        session.exec(
            select(Resolution.item_id).join(Item).where(Item.project_id == project.id)
        ).all()
    )


def review_queue(
    session: Session, project: Project, limit: int = 50
) -> tuple[list[ReviewItem], int]:
    """Items with no resolution and no trusted majority, oldest first, and how many in all."""
    labels = _regular_labels(project, load_rows(session, project))
    resolved = _resolved_item_ids(session, project)

    pending: dict[int, list[Reason]] = {}
    for item_id, item_labels in labels.items():
        reasons = _review_reasons(item_labels)
        if reasons and item_id not in resolved:
            pending[item_id] = reasons

    page_ids = sorted(pending)[:limit]
    items = (
        {item.id: item for item in session.exec(select(Item).where(col(Item.id).in_(page_ids)))}
        if page_ids
        else {}
    )
    return (
        [
            ReviewItem(
                item=items[i],
                reasons=pending[i],
                labels=labels[i],
            )
            for i in page_ids
        ],
        len(pending),
    )


def final_labels(session: Session, project: Project) -> list[FinalLabel]:
    """Every regular item's final label, for export."""
    labels = _regular_labels(project, load_rows(session, project))
    resolutions = {
        r.item_id: r
        for r in session.exec(select(Resolution).join(Item).where(Item.project_id == project.id))
    }
    items = session.exec(
        select(Item)
        .where(Item.project_id == project.id, col(Item.gold_answer).is_(None))
        .order_by(col(Item.id))
    )
    result = []
    for item in items:
        item_labels = labels.get(item.id, [])
        if item.id in resolutions:
            value, source = resolutions[item.id].value, "resolution"
        else:
            value = _majority(item_labels)
            source = "majority" if value is not None else "unresolved"
        result.append(
            FinalLabel(
                item=item,
                value=value,
                source=source,
                labels=len(item_labels),
                flagged_labels=sum(label.flagged for label in item_labels),
            )
        )
    return result


def user_emails(session: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return {u.id: u.email for u in session.exec(select(User).where(col(User.id).in_(user_ids)))}
