from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.db import get_session
from app.deps import require_role
from app.models import Role, User
from app.panel import METRICS, Metric
from app.schemas import (
    CapabilityOut,
    PanelChart,
    PanelChartPointOut,
    PanelLineSummary,
    PanelMetricOut,
    PanelSeriesSummary,
    PanelSignalOut,
)
from app.services import panel_line
from app.services.panel_line import BASELINE_SUBGROUPS, MetricChart, Signal

router = APIRouter(prefix="/panel-line", tags=["panel line"])

staff_only = require_role(Role.admin, Role.reviewer)


@router.get("")
def summary(
    _: User = Depends(staff_only), session: Session = Depends(get_session)
) -> PanelLineSummary:
    """Status and capability of every line and metric, for the overview grid."""
    charts = panel_line.all_charts(session)
    return PanelLineSummary(
        baseline_subgroups=BASELINE_SUBGROUPS,
        lines=sorted({c.line for c in charts}),
        metrics=[_metric_out(m) for m in METRICS.values()],
        series=[
            PanelSeriesSummary(
                line=c.line,
                metric=c.metric.key,
                status=c.status,
                first_warning=_signal_out(c, c.first("warning")),
                first_alarm=_signal_out(c, c.first("alarm")),
                signals=len(c.monitored_signals),
                latest_mean=c.xbar[-1].mean,
                baseline_cpk=c.baseline_capability.cpk,
                recent_cpk=c.recent_capability.cpk,
            )
            for c in charts
        ],
    )


@router.get("/lines/{line}/metrics/{metric}")
def chart(
    line: str,
    metric: str,
    _: User = Depends(staff_only),
    session: Session = Depends(get_session),
) -> PanelChart:
    """X-bar/R and EWMA charts, signals and capability for one line and metric."""
    if metric not in METRICS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown metric")
    series = panel_line.load_subgroups(session, line=line, metric=metric)
    c = panel_line.metric_chart(line, METRICS[metric], series.get((line, metric), []))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No complete baseline for this line yet")
    return PanelChart(
        line=line,
        metric=_metric_out(c.metric),
        status=c.status,
        baseline_subgroups=BASELINE_SUBGROUPS,
        subgroup_size=c.limits.n,
        center=c.limits.grand_mean,
        xbar_ucl=c.limits.xbar_ucl,
        xbar_lcl=c.limits.xbar_lcl,
        r_center=c.limits.mean_range,
        r_ucl=c.limits.r_ucl,
        r_lcl=c.limits.r_lcl,
        points=[
            PanelChartPointOut(
                subgroup=s.index,
                measured_at=s.measured_at,
                lot=s.lot,
                mean=x.mean,
                range=x.range,
                z=x.z,
                ewma=e.ewma,
                ewma_ucl=e.ucl,
                ewma_lcl=e.lcl,
            )
            for s, x, e in zip(c.subgroups, c.xbar, c.ewma, strict=True)
        ],
        signals=[_signal_out(c, s) for s in c.signals],
        baseline_capability=CapabilityOut(**asdict(c.baseline_capability)),
        recent_capability=CapabilityOut(**asdict(c.recent_capability)),
    )


def _metric_out(m: Metric) -> PanelMetricOut:
    return PanelMetricOut(**asdict(m))


def _signal_out(c: MetricChart, s: Signal | None) -> PanelSignalOut | None:
    if s is None:
        return None
    at = next(g.measured_at for g in c.subgroups if g.index == s.subgroup)
    return PanelSignalOut(
        subgroup=s.subgroup,
        measured_at=at,
        rule=s.rule,
        description=s.description,
        severity=s.severity,
        above=s.above,
    )
