"""Statistics for labeler quality. Pure functions with no database access, so each one
can be unit tested against worked examples.

Control charts follow the usual SPC conventions: a p-chart tracks a proportion
(here, the share of gold questions a labeler gets wrong) per subgroup, with limits at
three standard errors around the center line, and the Western Electric rules flag
patterns that are unlikely when the process is in control.
"""

import math
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations


def cohens_kappa(pairs: Sequence[tuple[Hashable, Hashable]]) -> float | None:
    """Agreement between two raters beyond chance, from their labels on shared items.

    Returns None when there are no pairs, or when chance agreement is already total
    (both raters used one and the same category for everything), where kappa is undefined.
    """
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(a == b for a, b in pairs) / n
    counts_a = Counter(a for a, _ in pairs)
    counts_b = Counter(b for _, b in pairs)
    expected = sum(counts_a[c] * counts_b[c] for c in counts_a) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def fleiss_kappa(ratings: Sequence[Sequence[Hashable]]) -> float | None:
    """Agreement among a fixed number of raters per item, beyond chance.

    `ratings` has one entry per item, each holding that item's labels (the raters may
    differ from item to item, but every item needs the same number of labels, at least 2).
    """
    if not ratings:
        return None
    raters = len(ratings[0])
    if raters < 2 or any(len(r) != raters for r in ratings):
        raise ValueError("every item needs the same number of labels, at least 2")

    items = len(ratings)
    category_totals: Counter[Hashable] = Counter()
    per_item_agreement = 0.0
    for labels in ratings:
        counts = Counter(labels)
        category_totals.update(counts)
        per_item_agreement += (sum(c * c for c in counts.values()) - raters) / (
            raters * (raters - 1)
        )

    observed = per_item_agreement / items
    total = items * raters
    expected = sum((t / total) ** 2 for t in category_totals.values())
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def pairwise_kappas(
    labels_by_item: dict[int, dict[int, Hashable]],
) -> dict[tuple[int, int], tuple[float | None, int]]:
    """Cohen's kappa for every pair of raters over the items they both labeled.

    `labels_by_item` maps item id to {rater id: label}. Returns
    {(rater_a, rater_b): (kappa, shared item count)} with rater_a < rater_b.
    """
    shared: dict[tuple[int, int], list[tuple[Hashable, Hashable]]] = {}
    for by_rater in labels_by_item.values():
        for a, b in combinations(sorted(by_rater), 2):
            shared.setdefault((a, b), []).append((by_rater[a], by_rater[b]))
    return {pair: (cohens_kappa(p), len(p)) for pair, p in shared.items()}


@dataclass(frozen=True)
class ChartPoint:
    defects: int
    size: int
    p: float
    center: float
    sigma: float
    ucl: float
    lcl: float

    @property
    def z(self) -> float:
        """Distance from the center line in standard errors."""
        return (self.p - self.center) / self.sigma


def p_chart(subgroups: Sequence[tuple[int, int]], center: float) -> list[ChartPoint]:
    """Points and three-sigma limits for a p-chart with a given center line.

    `subgroups` holds (defects, size) per subgroup; sizes may differ, so each point gets
    its own limits. The center is a standard (a target rate), not estimated from the data,
    so a labeler who is consistently worse than target shows up as out of control.
    """
    if not 0 < center < 1:
        raise ValueError("center must be strictly between 0 and 1")
    points = []
    for defects, size in subgroups:
        if size <= 0 or not 0 <= defects <= size:
            raise ValueError(f"bad subgroup: {defects} defects out of {size}")
        sigma = math.sqrt(center * (1 - center) / size)
        points.append(
            ChartPoint(
                defects=defects,
                size=size,
                p=defects / size,
                center=center,
                sigma=sigma,
                ucl=min(1.0, center + 3 * sigma),
                lcl=max(0.0, center - 3 * sigma),
            )
        )
    return points


class Rule(StrEnum):
    beyond_3_sigma = "beyond_3_sigma"
    two_of_three_beyond_2_sigma = "two_of_three_beyond_2_sigma"
    four_of_five_beyond_1_sigma = "four_of_five_beyond_1_sigma"
    eight_on_one_side = "eight_on_one_side"


RULE_DESCRIPTIONS = {
    Rule.beyond_3_sigma: "One point beyond the 3-sigma limit",
    Rule.two_of_three_beyond_2_sigma: "2 of 3 points in a row beyond 2 sigma on one side",
    Rule.four_of_five_beyond_1_sigma: "4 of 5 points in a row beyond 1 sigma on one side",
    Rule.eight_on_one_side: "8 points in a row on one side of the center line",
}


@dataclass(frozen=True)
class Violation:
    rule: Rule
    index: int  # the point that completes the pattern
    above: bool  # True when worse than target (error rate too high)


def western_electric(z: Sequence[float]) -> list[Violation]:
    """Check z-scores (distance from center in sigmas) against the four Western Electric
    rules. Each point is reported once, under the first rule it breaks, in rule order."""
    violations = []
    for i in range(len(z)):
        for rule, window, needed, threshold in (
            (Rule.beyond_3_sigma, 1, 1, 3.0),
            (Rule.two_of_three_beyond_2_sigma, 3, 2, 2.0),
            (Rule.four_of_five_beyond_1_sigma, 5, 4, 1.0),
            (Rule.eight_on_one_side, 8, 8, 0.0),
        ):
            if i + 1 < window:
                continue
            recent = z[i + 1 - window : i + 1]
            # The completing point must itself be on the flagged side, so a pattern is
            # reported where it is completed, not again on every later point.
            if z[i] > threshold and sum(v > threshold for v in recent) >= needed:
                violations.append(Violation(rule, i, above=True))
                break
            if z[i] < -threshold and sum(v < -threshold for v in recent) >= needed:
                violations.append(Violation(rule, i, above=False))
                break
    return violations
