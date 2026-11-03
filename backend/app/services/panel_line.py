"""Control charts and capability for each production line and panel metric.

For every (line, metric) series:
- Limits come from the first BASELINE_SUBGROUPS subgroups (phase I), and every subgroup
  is then judged against those fixed limits (phase II).
- Signals: the Western Electric rules on the X-bar chart, a range beyond the R chart's
  upper limit, and the EWMA leaving its limits. A point beyond 3 sigma or a range beyond
  its limit is an alarm; the rest are warnings (see ALARM_RULES). Signals inside the
  baseline are reported but don't set the status, since the baseline is what "in
  control" was defined as.
- Capability: Cpk for the baseline and for the most recent day, so a drift shows up as
  the margin to spec shrinking even before any panel fails.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import PanelMeasurement
from app.panel import METRICS, Metric
from app.spc import (
    Capability,
    EwmaPoint,
    XbarRLimits,
    XbarRPoint,
    capability,
    ewma_chart,
    xbar_r_chart,
    xbar_r_limits,
)
from app.stats import RULE_DESCRIPTIONS, Rule, western_electric

BASELINE_SUBGROUPS = 24  # the first three days at one subgroup every three hours
RECENT_SUBGROUPS = 8  # "the most recent day", for current capability
EWMA_LAMBDA = 0.2

RANGE_RULE = "range_beyond_ucl"
EWMA_RULE = "ewma_beyond_limit"
# Signals that stop the line: the Shewhart action limits. The zone rules (2 of 3 beyond
# 2 sigma, 4 of 5 beyond 1 sigma, 8 on one side) and the EWMA are early warnings. Each
# chart has a small false alarm rate per point, and twenty charts are watched at once, so
# treating every rule as an alarm would stop a healthy line most weeks.
ALARM_RULES = {str(Rule.beyond_3_sigma), RANGE_RULE}
SIGNAL_DESCRIPTIONS = {
    **{str(rule): text for rule, text in RULE_DESCRIPTIONS.items()},
    RANGE_RULE: "Subgroup range above the R chart's upper limit",
    EWMA_RULE: "EWMA outside its control limits",
}


@dataclass(frozen=True)
class Subgroup:
    index: int
    measured_at: datetime  # when its first panel was tested
    lot: str
    values: list[float]


@dataclass(frozen=True)
class Signal:
    subgroup: int
    rule: str
    above: bool  # True when the value is high (above the center line)

    @property
    def description(self) -> str:
        return SIGNAL_DESCRIPTIONS[self.rule]

    @property
    def severity(self) -> str:
        return "alarm" if self.rule in ALARM_RULES else "warning"


@dataclass(frozen=True)
class MetricChart:
    line: str
    metric: Metric
    subgroups: list[Subgroup]
    limits: XbarRLimits
    xbar: list[XbarRPoint]
    ewma: list[EwmaPoint]
    signals: list[Signal]
    baseline_capability: Capability
    recent_capability: Capability

    @property
    def monitored_signals(self) -> list[Signal]:
        return [s for s in self.signals if s.subgroup >= BASELINE_SUBGROUPS]

    @property
    def status(self) -> str:
        """out_of_control on any alarm after the baseline, warning on zone rules alone."""
        severities = {s.severity for s in self.monitored_signals}
        if "alarm" in severities:
            return "out_of_control"
        return "warning" if severities else "in_control"

    def first(self, severity: str) -> Signal | None:
        """The earliest alarm or warning after the baseline."""
        return next((s for s in self.monitored_signals if s.severity == severity), None)


def load_subgroups(
    session: Session, line: str | None = None, metric: str | None = None
) -> dict[tuple[str, str], list[Subgroup]]:
    """Measurements grouped into subgroups, keyed by (line, metric), oldest first."""
    query = select(
        PanelMeasurement.line,
        PanelMeasurement.metric,
        PanelMeasurement.subgroup,
        PanelMeasurement.lot,
        PanelMeasurement.value,
        PanelMeasurement.measured_at,
    ).order_by(col(PanelMeasurement.subgroup), col(PanelMeasurement.measured_at))
    if line is not None:
        query = query.where(PanelMeasurement.line == line)
    if metric is not None:
        query = query.where(PanelMeasurement.metric == metric)

    grouped: dict[tuple[str, str, int], list] = defaultdict(list)
    for row in session.exec(query):
        grouped[(row.line, row.metric, row.subgroup)].append(row)

    series: dict[tuple[str, str], list[Subgroup]] = defaultdict(list)
    for (ln, mt, index), rows in grouped.items():
        series[(ln, mt)].append(
            Subgroup(
                index=index,
                measured_at=rows[0].measured_at,
                lot=rows[0].lot,
                values=[r.value for r in rows],
            )
        )
    return dict(series)


def metric_chart(line: str, metric: Metric, subgroups: list[Subgroup]) -> MetricChart | None:
    """Charts for one series, or None until the baseline is complete."""
    if len(subgroups) <= BASELINE_SUBGROUPS:
        return None
    values = [s.values for s in subgroups]
    limits = xbar_r_limits(values[:BASELINE_SUBGROUPS])
    xbar = xbar_r_chart(values, limits)
    ewma = ewma_chart(
        [p.mean for p in xbar], target=limits.grand_mean, sigma=limits.sigma_xbar, lam=EWMA_LAMBDA
    )

    signals = [
        Signal(subgroups[v.index].index, str(v.rule), v.above)
        for v in western_electric([p.z for p in xbar])
    ]
    signals += [
        Signal(s.index, RANGE_RULE, above=True)
        for s, p in zip(subgroups, xbar, strict=True)
        if p.range > limits.r_ucl
    ]
    signals += [
        Signal(s.index, EWMA_RULE, above=p.ewma > p.ucl)
        for s, p in zip(subgroups, ewma, strict=True)
        if p.out_of_control
    ]
    signals.sort(key=lambda s: s.subgroup)

    def flat(groups: list[list[float]]) -> list[float]:
        return [v for g in groups for v in g]

    recent = values[-RECENT_SUBGROUPS:]
    recent_within = xbar_r_limits(recent).sigma_within
    return MetricChart(
        line=line,
        metric=metric,
        subgroups=subgroups,
        limits=limits,
        xbar=xbar,
        ewma=ewma,
        signals=signals,
        baseline_capability=capability(
            flat(values[:BASELINE_SUBGROUPS]), metric.lsl, metric.usl, limits.sigma_within
        ),
        recent_capability=capability(flat(recent), metric.lsl, metric.usl, recent_within),
    )


def all_charts(session: Session) -> list[MetricChart]:
    """A chart for every line and metric with enough data, in line then catalog order."""
    series = load_subgroups(session)
    charts = []
    for line in sorted({ln for ln, _ in series}):
        for key, metric in METRICS.items():
            chart = metric_chart(line, metric, series.get((line, key), []))
            if chart is not None:
                charts.append(chart)
    return charts
