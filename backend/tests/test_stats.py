import math

import pytest

from app.stats import (
    Rule,
    cohens_kappa,
    fleiss_kappa,
    p_chart,
    pairwise_kappas,
    western_electric,
)


def test_cohens_kappa_textbook_example():
    # Two raters, 50 items: yes/yes 20, yes/no 5, no/yes 10, no/no 15.
    # Observed 0.7, chance 0.5, so kappa = 0.4.
    pairs = [("yes", "yes")] * 20 + [("yes", "no")] * 5 + [("no", "yes")] * 10 + [("no", "no")] * 15
    assert cohens_kappa(pairs) == pytest.approx(0.4)


def test_cohens_kappa_edge_cases():
    assert cohens_kappa([]) is None
    assert cohens_kappa([("a", "a"), ("b", "b")]) == pytest.approx(1.0)
    # Both raters always say "a": agreement is total but so is chance agreement.
    assert cohens_kappa([("a", "a")] * 5) is None
    # Systematic disagreement is worse than chance.
    assert cohens_kappa([("a", "b"), ("b", "a")]) == pytest.approx(-1.0)


def test_fleiss_kappa_textbook_example():
    # Fleiss (1971) as worked on Wikipedia: 10 items, 14 raters, 5 categories.
    counts = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    ratings = [[c for c, n in enumerate(row) for _ in range(n)] for row in counts]
    assert fleiss_kappa(ratings) == pytest.approx(0.210, abs=5e-4)


def test_fleiss_kappa_edge_cases():
    assert fleiss_kappa([]) is None
    assert fleiss_kappa([["a", "a", "a"], ["b", "b", "b"]]) == pytest.approx(1.0)
    assert fleiss_kappa([["a", "a"], ["a", "a"]]) is None
    with pytest.raises(ValueError):
        fleiss_kappa([["a", "b"], ["a", "b", "c"]])
    with pytest.raises(ValueError):
        fleiss_kappa([["a"], ["b"]])


def test_pairwise_kappas_uses_only_shared_items():
    labels = {
        1: {10: "cat", 20: "cat", 30: "dog"},
        2: {10: "dog", 20: "dog"},
        3: {10: "cat", 30: "cat"},
    }
    result = pairwise_kappas(labels)
    assert set(result) == {(10, 20), (10, 30), (20, 30)}
    assert result[(10, 20)] == (pytest.approx(1.0), 2)
    assert result[(20, 30)][1] == 1


def test_p_chart_limits():
    [big, small] = p_chart([(19, 100), (1, 4)], center=0.1)

    assert big.sigma == pytest.approx(0.03)
    assert big.ucl == pytest.approx(0.19)
    assert big.lcl == pytest.approx(0.01)
    assert big.z == pytest.approx(3.0)

    # Small subgroups get wider limits, and the lower limit is clipped at 0.
    assert small.sigma == pytest.approx(math.sqrt(0.09 / 4))
    assert small.lcl == 0.0
    assert small.p == 0.25


def test_p_chart_rejects_bad_input():
    with pytest.raises(ValueError):
        p_chart([(1, 10)], center=0)
    with pytest.raises(ValueError):
        p_chart([(11, 10)], center=0.1)
    with pytest.raises(ValueError):
        p_chart([(0, 0)], center=0.1)


def rules_at(z: list[float]) -> list[tuple[Rule, int, bool]]:
    return [(v.rule, v.index, v.above) for v in western_electric(z)]


def test_in_control_process_has_no_violations():
    assert rules_at([0.5, -0.4, 1.2, -1.1, 0.3, 0.0, -0.8, 1.5, -1.9, 0.6]) == []


def test_rule_1_one_point_beyond_3_sigma():
    assert rules_at([0, 0, 3.4, 0]) == [(Rule.beyond_3_sigma, 2, True)]
    assert rules_at([0, -3.1]) == [(Rule.beyond_3_sigma, 1, False)]


def test_rule_2_two_of_three_beyond_2_sigma():
    assert rules_at([2.5, 0.0, 2.2]) == [(Rule.two_of_three_beyond_2_sigma, 2, True)]
    # Opposite sides don't count together.
    assert rules_at([2.5, 0.0, -2.2]) == []


def test_rule_3_four_of_five_beyond_1_sigma():
    assert rules_at([1.5, 1.2, 0.0, 1.1, 1.3]) == [(Rule.four_of_five_beyond_1_sigma, 4, True)]


def test_rule_4_eight_in_a_row_on_one_side():
    z = [0.5] * 7 + [0.2]
    assert rules_at(z) == [(Rule.eight_on_one_side, 7, True)]
    assert rules_at([0.5] * 7 + [-0.2]) == []


def test_each_point_reported_once_under_its_first_rule():
    # Point 2 breaks rules 1 and 2; only rule 1 is reported for it.
    assert rules_at([2.5, 0.0, 3.5]) == [(Rule.beyond_3_sigma, 2, True)]
