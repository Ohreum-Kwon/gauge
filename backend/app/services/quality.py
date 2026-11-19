"""Labeler quality for a project: gold accuracy, control charts, agreement, and speed.

Loads the project's labels once and hands them to the pure functions in app.stats.
A project's labels fit comfortably in memory at portfolio scale; at production scale
the per-day gold counts would move into SQL (GROUP BY user, day).
"""

import statistics
from collections import Counter, defaultdict
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
# Days a model labeler's agreement chart uses to set its own center line, and the fewest
# compared labels in them for the chart to be drawn at all.
JUDGE_BASELINE_DAYS = 3
JUDGE_MIN_BASELINE = 30


@dataclass(frozen=True)
class LabelRow:
    user_id: int
    item_id: int
    value: str
    gold_answer: str | None
    created_at: datetime
    time_spent_ms: int
    is_model: bool = False  # given by a model labeler (an LLM judge)
    model_version: str | None = None
    batch: str | None = None  # the upload the item came in

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
    # For a model labeler: the model version that gave most of the day's labels.
    model_version: str | None = None


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
class JudgeAgreementChart:
    """A model labeler's daily disagreement with people who are in control.

    Unlike the gold p-chart, the center isn't a target: it is the judge's own
    disagreement rate over its first `baseline_days` days (phase I), so the chart asks
    "did the judge change?" and works on every item people labeled, gold or not.
    """

    center: float
    baseline_days: int
    reference_user_ids: list[int]
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
    model_version: str | None = None  # a model labeler's latest version

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
            User.is_model,
            Label.model_version,
            Item.batch,
        )
        .join(Item)
        .join(User, col(User.id) == Label.user_id)
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
    versions = _versions_by_day(rows)
    return LabelerChart(
        center=project.target_error_rate,
        days=[ChartDay(d, p, versions.get(d)) for d, p in zip(days, points, strict=True)],
        alerts=[Alert(days[v.index], v) for v in violations],
    )


def _versions_by_day(rows: list[LabelRow]) -> dict[date, str]:
    counts: dict[date, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.model_version is not None:
            counts[row.created_at.date()][row.model_version] += 1
    return {day: c.most_common(1)[0][0] for day, c in counts.items()}


def majority_answers(rows: list[LabelRow]) -> dict[int, str]:
    """Each item's most common answer among `rows`; items where the top answers tie are
    left out."""
    votes: dict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        votes[row.item_id][row.value] += 1
    answers: dict[int, str] = {}
    for item_id, counter in votes.items():
        top = counter.most_common(2)
        if len(top) == 1 or top[0][1] > top[1][1]:
            answers[item_id] = top[0][0]
    return answers


def judge_agreement_chart(
    judge_rows: list[LabelRow], reference_rows: list[LabelRow]
) -> JudgeAgreementChart | None:
    """How often the judge disagrees with the reference people, per day of the judge's
    labels. On an item several reference people labeled, the judge is compared with
    their majority (items where they tie are skipped). None until the baseline days
    hold enough compared labels to set a center line."""
    reference = majority_answers(reference_rows)

    disagree: dict[date, int] = defaultdict(int)
    sizes: dict[date, int] = defaultdict(int)
    for row in judge_rows:
        if row.item_id in reference:
            day = row.created_at.date()
            sizes[day] += 1
            disagree[day] += row.value != reference[row.item_id]
    days = sorted(sizes)
    baseline = days[:JUDGE_BASELINE_DAYS]
    baseline_n = sum(sizes[d] for d in baseline)
    if len(days) <= JUDGE_BASELINE_DAYS or baseline_n < JUDGE_MIN_BASELINE:
        return None
    # Keep the center strictly inside (0, 1) so the limits stay defined.
    center = min(0.99, max(0.01, sum(disagree[d] for d in baseline) / baseline_n))
    points = p_chart([(disagree[d], sizes[d]) for d in days], center=center)
    violations = western_electric([p.z for p in points])
    versions = _versions_by_day(judge_rows)
    return JudgeAgreementChart(
        center=center,
        baseline_days=len(baseline),
        reference_user_ids=sorted({r.user_id for r in reference_rows}),
        days=[ChartDay(d, p, versions.get(d)) for d, p in zip(days, points, strict=True)],
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
        model_version=next((r.model_version for r in reversed(rows) if r.model_version), None),
    )


def agreement(project: Project, rows: list[LabelRow]) -> Agreement:
    """Agreement on regular (non-gold) items labeled by more than one labeler.

    Pairwise kappas include model labelers (how well does the judge agree with each
    person?); Fleiss' kappa is among people only, since the judge labels in shadow mode
    on top of an item's required labels."""
    by_item: dict[int, dict[int, str]] = defaultdict(dict)
    models: set[int] = set()
    for row in rows:
        if not row.is_gold:
            by_item[row.item_id][row.user_id] = row.value
            if row.is_model:
                models.add(row.user_id)
    shared = {item: labels for item, labels in by_item.items() if len(labels) > 1}

    # Fleiss' kappa needs the same number of raters on every item; use completed
    # overlap items only.
    k = project.overlap_labelers
    people = (
        [v for user_id, v in labels.items() if user_id not in models] for labels in shared.values()
    )
    complete = [labels for labels in people if len(labels) == k]
    return Agreement(
        fleiss_kappa=fleiss_kappa(complete) if complete else None,
        overlap_items=len(complete),
        raters_per_item=k,
        pairs=[
            PairAgreement(a, b, kappa, n)
            for (a, b), (kappa, n) in sorted(pairwise_kappas(shared).items())
        ],
    )


def project_labelers(session: Session, project: Project) -> list[User]:
    return session.exec(
        select(User)
        .join(ProjectMember)
        .where(ProjectMember.project_id == project.id, User.role == Role.labeler)
        .order_by(col(User.id))
    ).all()


def project_quality(session: Session, project: Project) -> tuple[list[LabelerQuality], Agreement]:
    rows = load_rows(session, project)
    by_user = _by_user(rows)
    return (
        [
            labeler_quality(project, u, by_user.get(u.id, []))
            for u in project_labelers(session, project)
        ],
        agreement(project, rows),
    )


def judge_chart_for(session: Session, project: Project, judge: User) -> JudgeAgreementChart | None:
    """The judge's agreement chart against the people who are currently in control."""
    rows = load_rows(session, project)
    by_user = _by_user(rows)
    reference_ids = {
        u.id
        for u in project_labelers(session, project)
        if not u.is_model
        and labeler_quality(project, u, by_user.get(u.id, [])).status == "in_control"
    }
    reference = [r for uid in reference_ids for r in by_user.get(uid, [])]
    return judge_agreement_chart(by_user.get(judge.id, []), reference)


def _by_user(rows: list[LabelRow]) -> dict[int, list[LabelRow]]:
    by_user: dict[int, list[LabelRow]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    return by_user
