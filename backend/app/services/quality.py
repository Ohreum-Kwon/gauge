"""Labeler quality for a project: gold accuracy, control charts, agreement, and speed.

Loads the project's labels once and hands them to the pure functions in app.stats.
A project's labels fit comfortably in memory at portfolio scale; at production scale
the per-day gold counts would move into SQL (GROUP BY user, day).
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.models import Item, Label, Project, ProjectMember, Role, User
from app.stats import (
    RULE_DESCRIPTIONS,
    ChartPoint,
    Violation,
    fleiss_kappa,
    p_chart,
    pairwise_kappas,
    western_electric,
)

# Below this many gold answers, accuracy and charts are too noisy to judge anyone by.
MIN_GOLD_FOR_STATUS = 10
# A labeler is flagged while an upward violation sits in their last few subgroups.
RECENT_SUBGROUPS = 3
# Labels faster than this are counted as possible rushing.
FAST_LABEL_MS = 1000


@dataclass(frozen=True)
class LabelRow:
    user_id: int
    item_id: int
    value: str
    gold_answer: str | None
    created_at: datetime
    time_spent_ms: int

    @property
    def is_gold(self) -> bool:
        return self.gold_answer is not None

    @property
    def is_error(self) -> bool:
        return self.gold_answer is not None and self.value != self.gold_answer


@dataclass(frozen=True)
class ChartDay:
    day: date
    point: ChartPoint


@dataclass(frozen=True)
class Alert:
    day: date
    violation: Violation

    @property
    def description(self) -> str:
        return RULE_DESCRIPTIONS[self.violation.rule]


@dataclass(frozen=True)
class LabelerChart:
    center: float
    days: list[ChartDay]
    alerts: list[Alert]


@dataclass(frozen=True)
class LabelerQuality:
    user: User
    labels: int
    gold_answered: int
    gold_correct: int
    median_time_ms: int | None
    fast_share: float | None
    status: str  # "in_control", "out_of_control" or "insufficient_data"
    latest_alert: Alert | None

    @property
    def accuracy(self) -> float | None:
        return self.gold_correct / self.gold_answered if self.gold_answered else None


@dataclass(frozen=True)
class PairAgreement:
    user_a: int
    user_b: int
    kappa: float | None
    shared_items: int


@dataclass(frozen=True)
class Agreement:
    fleiss_kappa: float | None
    overlap_items: int
    raters_per_item: int
    pairs: list[PairAgreement]


def load_rows(session: Session, project: Project, user_id: int | None = None) -> list[LabelRow]:
    query = (
        select(
            Label.user_id,
            Label.item_id,
            Label.value,
            Item.gold_answer,
            Label.created_at,
            Label.time_spent_ms,
        )
        .join(Item)
        .where(Item.project_id == project.id)
        .order_by(col(Label.created_at))
    )
    if user_id is not None:
        query = query.where(Label.user_id == user_id)
    return [LabelRow(*row) for row in session.exec(query)]


def labeler_chart(project: Project, rows: list[LabelRow]) -> LabelerChart:
    """One labeler's p-chart: gold error rate per day against the project's target."""
    errors: dict[date, int] = defaultdict(int)
    sizes: dict[date, int] = defaultdict(int)
    for row in rows:
        if row.is_gold:
            day = row.created_at.date()
            sizes[day] += 1
            errors[day] += row.is_error
    days = sorted(sizes)
    points = p_chart([(errors[d], sizes[d]) for d in days], center=project.target_error_rate)
    violations = western_electric([p.z for p in points])
    return LabelerChart(
        center=project.target_error_rate,
        days=[ChartDay(d, p) for d, p in zip(days, points, strict=True)],
        alerts=[Alert(days[v.index], v) for v in violations],
    )


def labeler_quality(project: Project, user: User, rows: list[LabelRow]) -> LabelerQuality:
    gold = [r for r in rows if r.is_gold]
    times = [r.time_spent_ms for r in rows]
    chart = labeler_chart(project, rows)
    upward = [a for a in chart.alerts if a.violation.above]
    recent_days = {d.day for d in chart.days[-RECENT_SUBGROUPS:]}

    if len(gold) < MIN_GOLD_FOR_STATUS or len(chart.days) < 2:
        status = "insufficient_data"
    elif any(a.day in recent_days for a in upward):
        status = "out_of_control"
    else:
        status = "in_control"

    return LabelerQuality(
        user=user,
        labels=len(rows),
        gold_answered=len(gold),
        gold_correct=sum(not r.is_error for r in gold),
        median_time_ms=int(statistics.median(times)) if times else None,
        fast_share=sum(t < FAST_LABEL_MS for t in times) / len(times) if times else None,
        status=status,
        latest_alert=upward[-1] if upward else None,
    )


def agreement(project: Project, rows: list[LabelRow]) -> Agreement:
    """Agreement on regular (non-gold) items labeled by more than one person."""
    by_item: dict[int, dict[int, str]] = defaultdict(dict)
    for row in rows:
        if not row.is_gold:
            by_item[row.item_id][row.user_id] = row.value
    shared = {item: labels for item, labels in by_item.items() if len(labels) > 1}

    # Fleiss' kappa needs the same number of raters on every item; use completed
    # overlap items only.
    k = project.overlap_labelers
    complete = [list(labels.values()) for labels in shared.values() if len(labels) == k]
    return Agreement(
        fleiss_kappa=fleiss_kappa(complete) if complete else None,
        overlap_items=len(complete),
        raters_per_item=k,
        pairs=[
            PairAgreement(a, b, kappa, n)
            for (a, b), (kappa, n) in sorted(pairwise_kappas(shared).items())
        ],
    )


def project_quality(session: Session, project: Project) -> tuple[list[LabelerQuality], Agreement]:
    rows = load_rows(session, project)
    by_user: dict[int, list[LabelRow]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)

    labelers = session.exec(
        select(User)
        .join(ProjectMember)
        .where(ProjectMember.project_id == project.id, User.role == Role.labeler)
        .order_by(col(User.id))
    ).all()
    return (
        [labeler_quality(project, u, by_user.get(u.id, [])) for u in labelers],
        agreement(project, rows),
    )
