from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.db import get_session
from app.deps import get_visible_project, require_role
from app.models import Project, ProjectMember, Role, User
from app.schemas import (
    AgreementOut,
    AlertOut,
    ChartPointOut,
    ControlChart,
    LabelerQualityOut,
    PairAgreementOut,
    ProjectQuality,
)
from app.services import quality

router = APIRouter(prefix="/projects/{project_id}/quality", tags=["quality"])

staff_only = require_role(Role.admin, Role.reviewer)


@router.get("")
def project_quality(
    project: Project = Depends(get_visible_project),
    _: User = Depends(staff_only),
    session: Session = Depends(get_session),
) -> ProjectQuality:
    """Every labeler's gold accuracy, control-chart status and speed, plus agreement."""
    labelers, agreement = quality.project_quality(session, project)
    return ProjectQuality(
        target_error_rate=project.target_error_rate,
        labelers=[_labeler_out(q) for q in labelers],
        agreement=AgreementOut(
            fleiss_kappa=agreement.fleiss_kappa,
            overlap_items=agreement.overlap_items,
            raters_per_item=agreement.raters_per_item,
            pairs=[
                PairAgreementOut(
                    user_a=p.user_a, user_b=p.user_b, kappa=p.kappa, shared_items=p.shared_items
                )
                for p in agreement.pairs
            ],
        ),
    )


@router.get("/labelers/{user_id}/chart")
def labeler_chart(
    user_id: int,
    project: Project = Depends(get_visible_project),
    _: User = Depends(staff_only),
    session: Session = Depends(get_session),
) -> ControlChart:
    """A labeler's p-chart: gold error rate per day, limits, and Western Electric alerts."""
    if session.get(ProjectMember, (project.id, user_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this project")
    chart = quality.labeler_chart(project, quality.load_rows(session, project, user_id=user_id))
    return ControlChart(
        user_id=user_id,
        center=chart.center,
        points=[
            ChartPointOut(
                day=d.day,
                gold_answered=d.point.size,
                errors=d.point.defects,
                error_rate=d.point.p,
                ucl=d.point.ucl,
                lcl=d.point.lcl,
            )
            for d in chart.days
        ],
        alerts=[_alert_out(a) for a in chart.alerts],
    )


def _alert_out(alert: quality.Alert) -> AlertOut:
    return AlertOut(
        day=alert.day,
        rule=alert.violation.rule,
        description=alert.description,
        above=alert.violation.above,
    )


def _labeler_out(q: quality.LabelerQuality) -> LabelerQualityOut:
    return LabelerQualityOut(
        user_id=q.user.id,
        email=q.user.email,
        labels=q.labels,
        gold_answered=q.gold_answered,
        gold_correct=q.gold_correct,
        accuracy=q.accuracy,
        median_time_ms=q.median_time_ms,
        fast_share=q.fast_share,
        status=q.status,
        latest_alert=_alert_out(q.latest_alert) if q.latest_alert else None,
    )
