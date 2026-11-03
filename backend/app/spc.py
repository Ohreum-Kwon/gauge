"""Control charts and capability for continuous measurements (variables data).

`stats.py` charts a proportion (a p-chart of gold errors). Panel measurements such as
luminance or threshold voltage are continuous, so they use variables charts instead:

- X-bar/R: each subgroup is a few panels measured in the same period. The X-bar chart
  tracks the subgroup mean and the R chart its range (spread within the subgroup).
- EWMA: an exponentially weighted moving average of the subgroup means. It reacts to
  small, slow shifts (a backlight dimming by a fraction of a sigma a day) sooner than
  X-bar does.
- Capability (Cp, Cpk, Pp, Ppk): how comfortably the process fits inside its spec limits.

Limits come from a baseline: the first subgroups, collected while the line was known to
be healthy (phase I). Later subgroups are judged against those fixed limits (phase II),
so a drift can't pull the limits along with it.

Like `stats.py`, everything here is a pure function with no database access.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# Shewhart constants by subgroup size n: (A2, D3, D4, d2). From ASTM STP 15D / Montgomery,
# Introduction to Statistical Quality Control, Appendix VI.
XBAR_R_CONSTANTS: dict[int, tuple[float, float, float, float]] = {
    2: (1.880, 0.0, 3.267, 1.128),
    3: (1.023, 0.0, 2.574, 1.693),
    4: (0.729, 0.0, 2.282, 2.059),
    5: (0.577, 0.0, 2.114, 2.326),
    6: (0.483, 0.0, 2.004, 2.534),
    7: (0.419, 0.076, 1.924, 2.704),
    8: (0.373, 0.136, 1.864, 2.847),
    9: (0.337, 0.184, 1.816, 2.970),
    10: (0.308, 0.223, 1.777, 3.078),
}


@dataclass(frozen=True)
class XbarRLimits:
    n: int  # subgroup size
    grand_mean: float  # X-double-bar, the X-bar chart's center line
    mean_range: float  # R-bar, the R chart's center line
    xbar_ucl: float
    xbar_lcl: float
    r_ucl: float
    r_lcl: float

    @property
    def sigma_within(self) -> float:
        """Short-term process sigma, estimated from the average range: R-bar / d2."""
        return self.mean_range / XBAR_R_CONSTANTS[self.n][3]

    @property
    def sigma_xbar(self) -> float:
        """Standard error of a subgroup mean: one third of the distance to a limit."""
        return (self.xbar_ucl - self.grand_mean) / 3


@dataclass(frozen=True)
class XbarRPoint:
    mean: float
    range: float
    z: float  # the mean's distance from the center line in standard errors


def _check_subgroups(subgroups: Sequence[Sequence[float]]) -> int:
    if not subgroups:
        raise ValueError("need at least one subgroup")
    n = len(subgroups[0])
    if any(len(s) != n for s in subgroups):
        raise ValueError("every subgroup needs the same size")
    if n not in XBAR_R_CONSTANTS:
        raise ValueError(f"subgroup size must be 2 to 10, got {n}")
    return n


def xbar_r_limits(baseline: Sequence[Sequence[float]]) -> XbarRLimits:
    """Phase I: X-bar and R chart limits from baseline subgroups of equal size."""
    n = _check_subgroups(baseline)
    a2, d3, d4, _ = XBAR_R_CONSTANTS[n]
    grand_mean = statistics.fmean(statistics.fmean(s) for s in baseline)
    mean_range = statistics.fmean(max(s) - min(s) for s in baseline)
    return XbarRLimits(
        n=n,
        grand_mean=grand_mean,
        mean_range=mean_range,
        xbar_ucl=grand_mean + a2 * mean_range,
        xbar_lcl=grand_mean - a2 * mean_range,
        r_ucl=d4 * mean_range,
        r_lcl=d3 * mean_range,
    )


def xbar_r_chart(subgroups: Sequence[Sequence[float]], limits: XbarRLimits) -> list[XbarRPoint]:
    """Phase II: plot subgroups against fixed limits. The z-scores feed
    `stats.western_electric` directly, the same rules the labeler p-charts use."""
    if _check_subgroups(subgroups) != limits.n:
        raise ValueError(f"subgroups must have size {limits.n}, like the baseline")
    sigma = limits.sigma_xbar
    points = []
    for s in subgroups:
        mean = statistics.fmean(s)
        z = (mean - limits.grand_mean) / sigma if sigma > 0 else 0.0
        points.append(XbarRPoint(mean=mean, range=max(s) - min(s), z=z))
    return points


@dataclass(frozen=True)
class EwmaPoint:
    value: float  # the plotted statistic (here, a subgroup mean)
    ewma: float
    ucl: float
    lcl: float

    @property
    def out_of_control(self) -> bool:
        return not self.lcl <= self.ewma <= self.ucl


def ewma_chart(
    values: Sequence[float],
    target: float,
    sigma: float,
    lam: float = 0.2,
    width: float = 3.0,
) -> list[EwmaPoint]:
    """EWMA chart: z_i = lam * x_i + (1 - lam) * z_(i-1), starting from the target.

    `sigma` is the standard deviation of the plotted values (for subgroup means, the
    X-bar chart's standard error). The limits start narrow and widen to their steady
    state, since early points average fewer observations. The Western Electric rules
    don't apply here: successive EWMA values are correlated by construction.
    """
    if not 0 < lam <= 1:
        raise ValueError("lam must be in (0, 1]")
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    points = []
    z = target
    for i, x in enumerate(values, start=1):
        z = lam * x + (1 - lam) * z
        half_width = width * sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * i)))
        points.append(EwmaPoint(value=x, ewma=z, ucl=target + half_width, lcl=target - half_width))
    return points


@dataclass(frozen=True)
class Capability:
    mean: float
    sigma_within: float  # short-term, from within-subgroup variation
    sigma_overall: float  # long-term, the sample standard deviation of every value
    cp: float | None  # None for a one-sided spec
    cpk: float
    pp: float | None
    ppk: float


def _index(mean: float, sigma: float, lsl: float | None, usl: float | None) -> float:
    sides = []
    if usl is not None:
        sides.append((usl - mean) / (3 * sigma))
    if lsl is not None:
        sides.append((mean - lsl) / (3 * sigma))
    return min(sides)


def capability(
    values: Sequence[float],
    lsl: float | None,
    usl: float | None,
    sigma_within: float | None = None,
) -> Capability:
    """Process capability against spec limits; either limit may be None (one-sided).

    Cp/Cpk use the short-term sigma (pass the X-bar/R chart's R-bar / d2). Without it,
    they fall back to the overall sigma, so Cpk equals Ppk. A Cpk of 1.33 or more is the
    usual bar for a capable process.
    """
    if lsl is None and usl is None:
        raise ValueError("need at least one spec limit")
    if lsl is not None and usl is not None and lsl >= usl:
        raise ValueError("lsl must be below usl")
    if len(values) < 2:
        raise ValueError("need at least two values")
    mean = statistics.fmean(values)
    overall = statistics.stdev(values)
    within = sigma_within if sigma_within is not None else overall
    if within <= 0 or overall <= 0:
        raise ValueError("values have no variation")
    two_sided = lsl is not None and usl is not None
    return Capability(
        mean=mean,
        sigma_within=within,
        sigma_overall=overall,
        cp=(usl - lsl) / (6 * within) if two_sided else None,  # type: ignore[operator]
        cpk=_index(mean, within, lsl, usl),
        pp=(usl - lsl) / (6 * overall) if two_sided else None,  # type: ignore[operator]
        ppk=_index(mean, overall, lsl, usl),
    )
