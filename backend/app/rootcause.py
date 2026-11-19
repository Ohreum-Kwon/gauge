"""Rank likely causes when a control chart raises an alert.

When a Western Electric rule fires, the useful next question is "what changed?". This
module answers it with plain arithmetic, so every ranking can be checked by hand:

1. **The shift.** The alert's run starts where a CUSUM change-point estimate puts the
   start of the shift that ends at the alert (see `run_start`). Points before it are the
   baseline. The shift's *extra errors* are the errors in the run minus what the
   baseline rate predicts for it. When there's too little baseline (a labeler bad from
   day one), the run is compared with the chart's center line instead.
2. **Candidates.** Each kind of cause gets a score from 0 to 1:
   - *A change at the onset* (a model update, a guideline edit, a new batch): the share
     of the extra errors that came after it, if it happened within two days before the
     run started (or during it).
   - *This labeler alone*: how much of their change the typical (median) other labeler
     did not share over the same days. 1 means everyone else held steady.
   - *A concentration* in one dimension (the item's true class, its upload batch, the
     shift it was labeled in): the largest gap between the share of extra errors a set
     of values holds and the share of answers it makes up. "3 classes hold 90% of the
     extra errors but 30% of the answers" scores 0.6. Errors spread evenly score ~0.
     Since the set is picked to look as bad as possible, it must also beat the rest of
     the run by a z of 3.5, and cover at most half the answers.
3. Candidates that clear a minimum score and a significance check (z of 2 or more) are
   ranked, each with a one-line explanation.

Pure functions with no database access, like `stats.py`.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

# A chart's subgroup: a calendar day on the labeler charts, a sample number in the live
# demo.
Period = date | int

# Fewer baseline answers than this, and the run is compared with the center line.
MIN_BASELINE = 30
# A peer needs this many answers on the same days to be compared with.
MIN_PEER = 10
# Pseudo-answers that pull a value's baseline rate toward the overall baseline rate, so a
# value seen twice before doesn't get a baseline of 0% or 100%.
SMOOTHING = 10
# A change this many days before the run started still counts as "at the onset".
EVENT_LEAD_DAYS = 2
MIN_SCORE = 0.15
MIN_Z = 2.0
# A concentration must also stand out from the rest of the run by this much, since the
# set of values is chosen to look as bad as possible.
MIN_CONTRAST_Z = 3.5
# A "concentration" covering more than this share of the answers isn't one.
MAX_CONCENTRATION_SHARE = 0.5
MAX_CAUSES = 5


class CauseKind(StrEnum):
    event = "event"
    labeler = "labeler"
    concentration = "concentration"


# Ties go to the more specific explanation.
KIND_ORDER = {CauseKind.event: 0, CauseKind.labeler: 1, CauseKind.concentration: 2}


@dataclass(frozen=True)
class Observation:
    """One charted answer: a gold answer (defect = wrong) or a compared judge label
    (defect = disagreed). `dims` holds the dimensions it can be grouped by."""

    at: datetime
    defect: bool
    dims: dict[str, str] = field(default_factory=dict)
    period: int | None = None  # set when subgroups aren't calendar days

    @property
    def day(self) -> Period:
        return self.at.date() if self.period is None else self.period


@dataclass(frozen=True)
class Event:
    kind: str
    description: str
    occurred_at: datetime
    period: int | None = None  # as on Observation

    @property
    def day(self) -> Period:
        return self.occurred_at.date() if self.period is None else self.period


def _periods_between(a: Period, b: Period) -> int:
    """b - a, in subgroups."""
    if isinstance(a, date) and isinstance(b, date):
        return (b - a).days
    return int(b) - int(a)  # type: ignore[arg-type]


def _short_day(period: Period) -> str:
    return f"on {period:%b %-d}" if isinstance(period, date) else f"at {period}"


@dataclass(frozen=True)
class Cause:
    kind: CauseKind
    title: str
    explanation: str
    score: float
    # The numbers behind the explanation, for the UI and for checking by hand.
    evidence: dict[str, float | int | str | list[str]]


@dataclass(frozen=True)
class Analysis:
    run_start: Period
    alert_day: Period
    compared_with: str  # "baseline" or "center"
    run_answers: int
    run_rate: float
    expected_rate: float
    extra_errors: float
    causes: list[Cause]


def _rate(obs: Sequence[Observation]) -> float:
    return sum(o.defect for o in obs) / len(obs) if obs else 0.0


def _z(defects: float, n: int, p: float) -> float:
    """How surprising `defects` out of `n` is at rate `p`, in standard errors."""
    p = min(max(p, 1e-3), 1 - 1e-3)
    return (defects - n * p) / math.sqrt(n * p * (1 - p)) if n else 0.0


def _two_proportion_z(d1: int, n1: int, d2: int, n2: int) -> float:
    pooled = (d1 + d2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    return (d1 / n1 - d2 / n2) / se if se > 0 else 0.0


def _pct(x: float) -> str:
    return f"{x:.0%}"


# A point counts toward the shift when it is more than this many sigmas above center
# (the CUSUM reference value, k = 0.5 for a 1-sigma shift).
CUSUM_K = 0.5


def run_start(days: Sequence[Period], z: Sequence[float], alert_day: Period) -> Period:
    """Where the shift that ends at the alert most likely began: the point i that
    maximizes sum(z[j] - k for j in i..alert), the change-point estimate behind an
    upper CUSUM. One unlucky low point inside a shift doesn't cut it short (and hide
    the change that started it), and a noisy high point just before it isn't pulled in.
    """
    end = list(days).index(alert_day)
    best, best_i, total = float("-inf"), end, 0.0
    for i in range(end, -1, -1):
        total += z[i] - CUSUM_K
        if total > best:
            best, best_i = total, i
    return days[best_i]


def analyze(
    obs: Sequence[Observation],
    days: Sequence[Period],
    z: Sequence[float],
    alert_day: Period,
    center: float,
    events: Sequence[Event] = (),
    peers: dict[str, Sequence[Observation]] | None = None,
    dimensions: dict[str, str] | None = None,
    subject: str = "this labeler",
    unit: str = "day",
    when: Callable[[Period], str] = _short_day,
) -> Analysis:
    """Rank causes for the alert on `alert_day` of a chart with points `days` and
    z-scores `z`. `peers` maps each other labeler to their observations (None skips
    the "this labeler alone" check), and `dimensions` maps each dimension key in
    `Observation.dims` to a readable name. `unit` names a subgroup ("day", "sample")
    and `when` phrases one ("on Nov 3", "at sample 40") in explanations."""
    start = run_start(days, z, alert_day)
    run = [o for o in obs if start <= o.day <= alert_day]
    before = [o for o in obs if o.day < start]
    use_baseline = len(before) >= MIN_BASELINE
    expected = _rate(before) if use_baseline else center
    extra = sum(o.defect for o in run) - len(run) * expected

    causes: list[Cause] = []
    if run and extra > 0:
        for event in events:
            cause = _event_cause(event, obs, run, start, alert_day, expected, unit, when)
            if cause:
                causes.append(cause)
        if peers is not None:
            cause = _labeler_cause(run, before, peers, start, alert_day, center, subject, unit)
            if cause:
                causes.append(cause)
        for key, name in (dimensions or {}).items():
            cause = _concentration_cause(key, name, run, before, expected, use_baseline)
            if cause:
                causes.append(cause)

    causes = [c for c in causes if c.score >= MIN_SCORE]
    causes.sort(key=lambda c: (-round(c.score, 2), KIND_ORDER[c.kind]))
    return Analysis(
        run_start=start,
        alert_day=alert_day,
        compared_with="baseline" if use_baseline else "center",
        run_answers=len(run),
        run_rate=_rate(run),
        expected_rate=expected,
        extra_errors=max(extra, 0.0),
        causes=causes[:MAX_CAUSES],
    )


def _event_cause(
    event: Event,
    obs: Sequence[Observation],
    run: Sequence[Observation],
    start: Period,
    alert_day: Period,
    expected: float,
    unit: str,
    when: Callable[[Period], str],
) -> Cause | None:
    lead = _periods_between(event.day, start)
    if lead > EVENT_LEAD_DAYS or _periods_between(alert_day, event.day) > 0:
        return None
    before = [o for o in obs if o.at < event.occurred_at]
    after = [o for o in obs if o.at >= event.occurred_at and o.day <= alert_day]
    if not before or not after:
        return None
    rate_before, rate_after = _rate(before), _rate(after)
    if _z(sum(o.defect for o in after), len(after), rate_before) < MIN_Z:
        return None
    run_after = [o for o in run if o.at >= event.occurred_at]
    extra_total = sum(o.defect for o in run) - len(run) * expected
    extra_after = sum(o.defect for o in run_after) - len(run_after) * expected
    share = min(1.0, max(0.0, extra_after / extra_total))

    if lead == 0:
        timing = f"the {unit} the shift began"
    elif lead < 0:
        timing = f"{-lead} {unit}{'s' if lead < -1 else ''} into the shift"
    else:
        timing = f"{lead} {unit}{'s' if lead > 1 else ''} before the shift began"
    return Cause(
        kind=CauseKind.event,
        title=event.description,
        explanation=(
            f"Happened {when(event.day)}, {timing}. Rate {_pct(rate_before)} before it, "
            f"{_pct(rate_after)} after."
        ),
        score=share,
        evidence={
            "event_kind": event.kind,
            "occurred_at": event.occurred_at.isoformat(),
            "rate_before": rate_before,
            "rate_after": rate_after,
            "share_of_extra_errors": share,
        },
    )


def _labeler_cause(
    run: Sequence[Observation],
    before: Sequence[Observation],
    peers: dict[str, Sequence[Observation]],
    start: Period,
    alert_day: Period,
    center: float,
    subject: str,
    unit: str,
) -> Cause | None:
    """Compare with the typical other labeler (the median), so one very bad peer
    doesn't make everyone else look worse than they are."""
    peers_run, peers_change = [], []
    for peer in peers.values():
        during = [o for o in peer if start <= o.day <= alert_day]
        prior = [o for o in peer if o.day < start]
        if len(during) >= MIN_PEER:
            peers_run.append(_rate(during))
            if len(prior) >= MIN_PEER:
                peers_change.append(_rate(during) - _rate(prior))
    if not peers_run:
        return None
    rate_run, peer_run = _rate(run), statistics.median(peers_run)
    defects = sum(o.defect for o in run)

    if len(before) >= MIN_BASELINE and peers_change:
        # Did everyone change at once, or only this labeler?
        rate_before, peer_change = _rate(before), statistics.median(peers_change)
        change = rate_run - rate_before
        if change <= 0 or _z(defects, len(run), rate_before) < MIN_Z:
            return None
        score = min(1.0, max(0.0, (change - max(peer_change, 0.0)) / change))
        return Cause(
            kind=CauseKind.labeler,
            title=f"Only {subject} changed",
            explanation=(
                f"{subject} went from {_pct(rate_before)} to {_pct(rate_run)}. The typical "
                f"other labeler changed by {peer_change:+.0%} over the same {unit}s."
            ),
            score=score,
            evidence={
                "rate_before": rate_before,
                "rate_during": rate_run,
                "median_peer_change": peer_change,
                "peers": len(peers_change),
            },
        )

    # No baseline: is this labeler worse than the typical other labeler on the same days?
    gap = rate_run - center
    if gap <= 0 or _z(defects, len(run), max(peer_run, center)) < MIN_Z:
        return None
    return Cause(
        kind=CauseKind.labeler,
        title=f"{subject} is worse than the others",
        explanation=(
            f"{subject} is at {_pct(rate_run)} on these {unit}s; the typical other labeler is "
            f"at {_pct(peer_run)} (target {_pct(center)})."
        ),
        score=min(1.0, max(0.0, (rate_run - max(peer_run, center)) / gap)),
        evidence={
            "rate_during": rate_run,
            "median_peer_rate": peer_run,
            "center": center,
            "peers": len(peers_run),
        },
    )


def _concentration_cause(
    key: str,
    name: str,
    run: Sequence[Observation],
    before: Sequence[Observation],
    expected: float,
    use_baseline: bool,
) -> Cause | None:
    run_by: dict[str, list[Observation]] = defaultdict(list)
    before_by: dict[str, list[Observation]] = defaultdict(list)
    for o in run:
        if key in o.dims:
            run_by[o.dims[key]].append(o)
    for o in before:
        if key in o.dims:
            before_by[o.dims[key]].append(o)
    if len(run_by) < 2:
        return None  # nothing to contrast

    def baseline_rate(value: str) -> float:
        if not use_baseline:
            return expected
        prior = before_by[value]
        return (sum(o.defect for o in prior) + SMOOTHING * expected) / (len(prior) + SMOOTHING)

    stats = []
    for value, rows in run_by.items():
        p0 = baseline_rate(value)
        stats.append((value, len(rows), sum(o.defect for o in rows), p0))
    excess = {v: d - n * p0 for v, n, d, p0 in stats}
    positive = sum(e for e in excess.values() if e > 0)
    if positive <= 0:
        return None
    total_n = sum(n for _, n, _, _ in stats)

    # Values from most to least extra errors per answer; take the prefix where the
    # share of extra errors most outruns the share of answers.
    stats.sort(key=lambda s: -excess[s[0]] / s[1])
    best, best_k, cum_e, cum_n = 0.0, 0, 0.0, 0
    for k, (value, n, _, _) in enumerate(stats, start=1):
        if excess[value] <= 0:
            break
        cum_e += excess[value]
        cum_n += n
        gap = cum_e / positive - cum_n / total_n
        if gap > best:
            best, best_k = gap, k
    if best_k == 0:
        return None

    chosen = stats[:best_k]
    n = sum(s[1] for s in chosen)
    d = sum(s[2] for s in chosen)
    p0 = sum(s[1] * s[3] for s in chosen) / n
    rest_n, rest_d = total_n - n, sum(s[2] for s in stats[best_k:])
    if n / total_n > MAX_CONCENTRATION_SHARE or _z(d, n, p0) < MIN_Z:
        return None
    if rest_n and _two_proportion_z(d, n, rest_d, rest_n) < MIN_CONTRAST_Z:
        return None
    values = [s[0] for s in chosen]
    share_errors = sum(excess[v] for v in values) / positive
    share_answers = n / total_n
    label = ", ".join(values) if len(values) <= 4 else f"{len(values)} {name} values"
    return Cause(
        kind=CauseKind.concentration,
        title=f"{name[0].upper()}{name[1:]}: {label}",
        explanation=(
            f"{label} {'holds' if len(values) == 1 else 'hold'} {_pct(share_errors)} of the "
            f"extra errors but {_pct(share_answers)} of the answers. Rate on "
            f"{'it' if len(values) == 1 else 'them'}: {_pct(p0)} expected, {_pct(d / n)} "
            "during the shift."
        ),
        score=best,
        evidence={
            "dimension": key,
            "values": values,
            "share_of_extra_errors": share_errors,
            "share_of_answers": share_answers,
            "rate_expected": p0,
            "rate_during": d / n,
        },
    )


def shift_of(at: datetime) -> str:
    """The 8-hour shift (UTC) a label was given in."""
    hour = at.hour
    if hour < 8:
        return "night (00-08 UTC)"
    if hour < 16:
        return "day (08-16 UTC)"
    return "evening (16-24 UTC)"
