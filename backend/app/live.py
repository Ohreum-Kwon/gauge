"""The live demo: labelers and a panel line that produce data in real time, with faults a
visitor can inject, judged by the same control chart code as the rest of Gauge.

Nothing here touches the database. Each visitor gets their own `LiveDemo`, so one
person's faults never show up on someone else's screen, and the free Postgres can sleep
while people watch. Every `step()` is one sample: a batch of gold answers from each
labeler and a subgroup of five panels from each line.

Because the demo knows which faults are active, it can grade its own detectors: an alarm
on a chart with a fault is a detection (with its delay in samples), and an alarm on a
healthy chart is a false alarm. Those happen: a 3-sigma limit is crossed by chance about
once in 370 points, and the demo says so rather than hiding it.
"""

import random
import statistics
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.panel import METRICS
from app.panel_sim import PANELS_PER_SUBGROUP, panel_readings
from app.spc import XbarRLimits, ewma_chart, xbar_r_chart, xbar_r_limits
from app.stats import RULE_DESCRIPTIONS, Rule, p_chart, western_electric

GOLD_PER_SAMPLE = 20  # gold answers per labeler per sample
TARGET_ERROR_RATE = 0.10
BASELINE_SAMPLES = 50  # panel subgroups used for phase I limits (sent as history on connect)
DRIFT_PER_SAMPLE = 0.03  # accuracy lost per sample by a drifting labeler
DRIFT_FLOOR = 0.60
RUSHER_ACCURACY = 0.10  # always clicking the first of ten classes
TFT_LOT_SAMPLES = 8  # a bad lot lasts this many subgroups
GRACE_SAMPLES = 8  # alarms this soon after a fault clears are its tail, not false alarms
EWMA_RULE = "ewma_beyond_limit"
RULE_TEXT = {**{r.value: d for r, d in RULE_DESCRIPTIONS.items()}, EWMA_RULE: "EWMA beyond limit"}

LABELERS = {"avery": 0.95, "blake": 0.94, "casey": 0.96}  # healthy gold accuracy
LINES = ("L1",)  # one line, two charts: few false alarms in a short visit
PANEL_METRICS = ("white_luminance", "tft_vth")


class Fault(StrEnum):
    drift = "drift"  # a labeler's accuracy slides from ~95% to 60%
    rush = "rush"  # a labeler starts clicking the first option
    backlight = "backlight"  # a line's backlights start ageing
    tft_lot = "tft_lot"  # a line builds from a lot with high threshold voltage


LABELER_FAULTS = {Fault.drift, Fault.rush}
LINE_FAULTS = {Fault.backlight, Fault.tft_lot}
# Which panel charts each line fault is expected to move.
FAULT_METRICS = {Fault.backlight: "white_luminance", Fault.tft_lot: "tft_vth"}


@dataclass
class ChartState:
    """Ground truth and detection bookkeeping for one chart."""

    fault: Fault | None = None
    fault_since: int | None = None
    detected: bool = False
    cleared_at: int | None = None

    def start(self, fault: Fault, sample: int) -> None:
        self.fault, self.fault_since, self.detected = fault, sample, False

    def clear(self, sample: int) -> None:
        if self.fault is not None:
            self.cleared_at = sample
        self.fault, self.fault_since, self.detected = None, None, False


@dataclass
class Labeler:
    accuracy: float
    healthy: float
    fault: Fault | None = None
    z: list[float] = field(default_factory=list)
    chart: ChartState = field(default_factory=ChartState)


@dataclass
class PanelChart:
    means: list[float] = field(default_factory=list)
    baseline: list[list[float]] = field(default_factory=list)
    limits: XbarRLimits | None = None
    z: list[float] = field(default_factory=list)
    chart: ChartState = field(default_factory=ChartState)


@dataclass
class Line:
    aged: int | None = None  # subgroups of backlight ageing so far; None when healthy
    lot_left: int = 0  # subgroups left in a bad TFT lot


class LiveDemo:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.sample = 0
        self.labelers = {name: Labeler(acc, acc) for name, acc in LABELERS.items()}
        self.lines = {line: Line() for line in LINES}
        self.charts = {(line, m): PanelChart() for line in LINES for m in PANEL_METRICS}
        self.pending: list[dict[str, Any]] = []  # events to send with the next sample

    @staticmethod
    def describe() -> dict[str, Any]:
        """What the client needs to draw the empty charts."""
        return {
            "target_error_rate": TARGET_ERROR_RATE,
            "gold_per_sample": GOLD_PER_SAMPLE,
            "baseline_samples": BASELINE_SAMPLES,
            "labelers": list(LABELERS),
            "lines": list(LINES),
            "metrics": [
                {"key": m, "name": METRICS[m].name, "unit": METRICS[m].unit} for m in PANEL_METRICS
            ],
            "faults": {
                "labeler": [f.value for f in LABELER_FAULTS],
                "line": [f.value for f in LINE_FAULTS],
            },
        }

    # Faults

    def inject(self, fault: Fault, target: str) -> None:
        """Start a fault on a labeler or a line. Raises KeyError for an unknown target or
        a fault that doesn't apply to it."""
        if fault in LABELER_FAULTS:
            labeler = self.labelers[target]
            labeler.fault = fault
            if fault is Fault.rush:
                labeler.accuracy = RUSHER_ACCURACY
            labeler.chart.start(fault, self.sample + 1)
        elif fault in LINE_FAULTS:
            line = self.lines[target]
            if fault is Fault.backlight:
                line.aged = 0
            else:
                line.lot_left = TFT_LOT_SAMPLES
            self.charts[target, FAULT_METRICS[fault]].chart.start(fault, self.sample + 1)
        else:  # pragma: no cover - the enum is exhaustive
            raise KeyError(fault)
        self.pending.append({"type": "fault", "fault": fault.value, "target": target})

    def reset(self) -> None:
        """Clear every fault: retrain the labelers, replace the backlights."""
        next_sample = self.sample + 1
        for labeler in self.labelers.values():
            labeler.accuracy, labeler.fault = labeler.healthy, None
            labeler.chart.clear(next_sample)
        for line in self.lines.values():
            line.aged, line.lot_left = None, 0
        for chart in self.charts.values():
            chart.chart.clear(next_sample)
        self.pending.append({"type": "reset"})

    # Sampling

    def step(self) -> dict[str, Any]:
        self.sample += 1
        events, self.pending = self.pending, []
        labelers = [self._step_labeler(name, lab, events) for name, lab in self.labelers.items()]
        panel = []
        for line_name, line in self.lines.items():
            subgroup = [
                panel_readings(self.rng, aged=line.aged or 0, shifted=line.lot_left > 0)
                for _ in range(PANELS_PER_SUBGROUP)
            ]
            for metric in PANEL_METRICS:
                values = [p[metric] for p in subgroup]
                panel.append(self._step_panel(line_name, metric, values, events))
            if line.aged is not None:
                line.aged += 1
            if line.lot_left:
                line.lot_left -= 1
                if not line.lot_left:
                    self.charts[line_name, "tft_vth"].chart.clear(self.sample + 1)
                    events.append({"type": "cleared", "fault": "tft_lot", "target": line_name})
        return {"sample": self.sample, "labelers": labelers, "panel": panel, "events": events}

    def _step_labeler(self, name: str, lab: Labeler, events: list) -> dict[str, Any]:
        if lab.fault is Fault.drift:
            lab.accuracy = max(DRIFT_FLOOR, lab.accuracy - DRIFT_PER_SAMPLE)
        errors = sum(self.rng.random() > lab.accuracy for _ in range(GOLD_PER_SAMPLE))
        (point,) = p_chart([(errors, GOLD_PER_SAMPLE)], TARGET_ERROR_RATE)
        lab.z = (lab.z + [point.z])[-8:]  # the longest Western Electric window
        rule = _latest_violation(lab.z, worse_only=True)
        self._grade(lab.chart, name, rule, events)
        return {
            "name": name,
            "error_rate": point.p,
            "center": point.center,
            "ucl": point.ucl,
            "lcl": point.lcl,
            "signal": "alarm" if rule else None,
            "rule": rule,
        }

    def _step_panel(self, line: str, metric: str, values: list[float], events: list):
        chart = self.charts[line, metric]
        mean = statistics.fmean(values)
        out: dict[str, Any] = {"line": line, "metric": metric, "mean": mean}
        if chart.limits is None:
            # Phase I: collect the baseline the limits come from.
            chart.baseline.append(values)
            if len(chart.baseline) == BASELINE_SAMPLES:
                chart.limits = xbar_r_limits(chart.baseline)
            return out | {"baseline": True, "signal": None, "rule": None}

        limits = chart.limits
        (point,) = xbar_r_chart([values], limits)
        chart.means.append(mean)
        chart.z = (chart.z + [point.z])[-8:]
        ewma = ewma_chart(chart.means, limits.grand_mean, limits.sigma_xbar)[-1]

        # As on the panel line page: beyond 3 sigma is an alarm; zone rules and the
        # EWMA are early warnings.
        rule = _latest_violation(chart.z, worse_only=False)
        if rule == Rule.beyond_3_sigma:
            signal = "alarm"
        elif rule or ewma.out_of_control:
            signal, rule = "warning", rule or EWMA_RULE
        else:
            signal = None
        self._grade(chart.chart, f"{line}:{metric}", rule if signal == "alarm" else None, events)
        return out | {
            "baseline": False,
            "center": limits.grand_mean,
            "ucl": limits.xbar_ucl,
            "lcl": limits.xbar_lcl,
            "ewma": ewma.ewma,
            "ewma_ucl": ewma.ucl,
            "ewma_lcl": ewma.lcl,
            "signal": signal,
            "rule": rule,
        }

    def _grade(self, state: ChartState, chart: str, alarm_rule: str | None, events: list):
        """Compare an alarm (or its absence) with the ground truth."""
        if alarm_rule is None:
            return
        base = {"chart": chart, "rule": alarm_rule, "description": RULE_TEXT[alarm_rule]}
        if state.fault is not None and state.fault_since is not None:
            if not state.detected:
                state.detected = True
                delay = self.sample - state.fault_since + 1
                events.append({"type": "detected", "fault": state.fault.value, "samples": delay})
                events[-1].update(base)
        elif state.cleared_at is None or self.sample - state.cleared_at >= GRACE_SAMPLES:
            events.append({"type": "false_alarm", **base})


def _latest_violation(z: list[float], worse_only: bool) -> str | None:
    """The Western Electric rule the newest point completes, if any. For labelers only
    the worse-than-target side counts; for panels either side is a problem."""
    for v in western_electric(z):
        if v.index == len(z) - 1 and (v.above or not worse_only):
            return v.rule.value
    return None
