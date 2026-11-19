"""Root-cause analysis for one alert on a labeler's chart: loads what app.rootcause needs.

Gold charts are explained from the labeler's gold answers, grouped by the gold answer's
class, the item's batch and the shift. A model labeler's agreement chart is explained
from its compared labels, grouped by the class the people chose. Peers are always the
other people (never model labelers), so a judge's update can't hide a person's drift,
and the other way around.
"""

from datetime import date

from sqlmodel import Session, col, or_, select

from app.models import Project, ProjectEvent, User
from app.rootcause import Analysis, Event, Observation, analyze, shift_of
from app.services import quality
from app.services.quality import LabelRow

GOLD_DIMENSIONS = {"class": "true class", "batch": "batch", "shift": "shift"}
AGREEMENT_DIMENSIONS = {"class": "class people chose", "shift": "shift"}


class NoSuchAlert(ValueError):
    pass


def _gold_observation(row: LabelRow) -> Observation:
    dims = {"class": row.gold_answer or "", "shift": shift_of(row.created_at)}
    if row.batch:
        dims["batch"] = row.batch
    return Observation(at=row.created_at, defect=row.is_error, dims=dims)


def project_events(session: Session, project: Project, user: User) -> list[ProjectEvent]:
    """Events that could affect `user`'s work: project-wide ones and their own."""
    return list(
        session.exec(
            select(ProjectEvent)
            .where(
                ProjectEvent.project_id == project.id,
                or_(col(ProjectEvent.user_id).is_(None), ProjectEvent.user_id == user.id),
            )
            .order_by(col(ProjectEvent.occurred_at))
        )
    )


def explain_alert(
    session: Session, project: Project, user: User, day: date, chart: str = "gold"
) -> Analysis:
    rows = quality.load_rows(session, project)
    mine = [r for r in rows if r.user_id == user.id]
    labelers = {u.id: u for u in quality.project_labelers(session, project)}
    people = {uid for uid, u in labelers.items() if not u.is_model and uid != user.id}
    events = [
        Event(e.kind.value, e.description, e.occurred_at)
        for e in project_events(session, project, user)
    ]
    subject = user.email

    if chart == "gold":
        result = quality.labeler_chart(project, mine)
        obs = [_gold_observation(r) for r in mine if r.is_gold]
        peers = {
            labelers[uid].email: [
                _gold_observation(r) for r in rows if r.user_id == uid and r.is_gold
            ]
            for uid in people
        }
        dimensions = GOLD_DIMENSIONS
    elif chart == "agreement":
        if not user.is_model:
            raise NoSuchAlert("Only model labelers have an agreement chart")
        result = quality.judge_chart_for(session, project, user)
        if result is None:
            raise NoSuchAlert("The agreement chart has no baseline yet")
        reference_ids = set(result.reference_user_ids)
        reference = quality.majority_answers([r for r in rows if r.user_id in reference_ids])
        obs = [
            Observation(
                at=r.created_at,
                defect=r.value != reference[r.item_id],
                dims={"class": reference[r.item_id], "shift": shift_of(r.created_at)},
            )
            for r in mine
            if r.item_id in reference
        ]
        peers = None  # people can't disagree with themselves
        dimensions = AGREEMENT_DIMENSIONS
    else:
        raise NoSuchAlert(f"Unknown chart {chart!r}")

    alert_days = {a.day for a in result.alerts if a.violation.above}
    if day not in alert_days:
        raise NoSuchAlert(f"No upward alert on {day.isoformat()}")
    return analyze(
        obs,
        days=[d.day for d in result.days],
        z=[d.point.z for d in result.days],
        alert_day=day,
        center=result.center,
        events=events,
        peers=peers,
        dimensions=dimensions,
        subject=subject,
    )
