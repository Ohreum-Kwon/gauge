import math
import random

import pytest

from app.spc import capability, ewma_chart, xbar_r_chart, xbar_r_limits
from app.stats import Rule, western_electric

BASELINE = [[1, 2, 3, 4, 5], [2, 3, 4, 5, 6], [3, 4, 5, 6, 7]]


def test_xbar_r_limits_worked_example():
    # Grand mean 4, R-bar 4, n = 5: A2 = 0.577, D3 = 0, D4 = 2.114, d2 = 2.326.
    limits = xbar_r_limits(BASELINE)
    assert limits.grand_mean == pytest.approx(4)
    assert limits.mean_range == pytest.approx(4)
    assert limits.xbar_ucl == pytest.approx(4 + 0.577 * 4)
    assert limits.xbar_lcl == pytest.approx(4 - 0.577 * 4)
    assert limits.r_ucl == pytest.approx(2.114 * 4)
    assert limits.r_lcl == 0
    assert limits.sigma_within == pytest.approx(4 / 2.326)
    # A2 is 3 / (d2 * sqrt(n)), so the two sigma estimates agree to rounding.
    assert limits.sigma_xbar == pytest.approx(limits.sigma_within / math.sqrt(5), rel=1e-3)


def test_xbar_r_chart_scores_against_fixed_limits():
    limits = xbar_r_limits(BASELINE)
    [on_target, shifted] = xbar_r_chart([[3, 4, 4, 4, 5], [7, 7, 7, 7, 7]], limits)
    assert on_target.mean == 4 and on_target.range == 2 and on_target.z == 0
    assert shifted.range == 0
    assert shifted.z == pytest.approx(3 / limits.sigma_xbar)
    assert western_electric([on_target.z, shifted.z])[0].rule == Rule.beyond_3_sigma


def test_xbar_r_rejects_bad_subgroups():
    with pytest.raises(ValueError):
        xbar_r_limits([])
    with pytest.raises(ValueError):
        xbar_r_limits([[1, 2], [1, 2, 3]])
    with pytest.raises(ValueError):
        xbar_r_limits([[1], [2]])
    with pytest.raises(ValueError):
        xbar_r_chart([[1, 2, 3]], xbar_r_limits(BASELINE))


def test_ewma_worked_example():
    # lam = 0.2: z1 = 0.2, z2 = 0.36. Limit half-widths 3 * sqrt(lam / (2 - lam) * (1 -
    # (1 - lam)^2i)): 0.6 at i = 1, about 0.768 at i = 2, approaching 1.
    first, second, *_, last = ewma_chart([1] * 50, target=0, sigma=1)
    assert first.ewma == pytest.approx(0.2)
    assert first.ucl == pytest.approx(0.6)
    assert first.lcl == pytest.approx(-0.6)
    assert second.ewma == pytest.approx(0.36)
    assert second.ucl == pytest.approx(3 * math.sqrt(0.2 / 1.8 * (1 - 0.8**4)))
    assert last.ucl == pytest.approx(1, abs=1e-6)


def test_ewma_catches_a_small_sustained_shift():
    rng = random.Random(1)
    in_control = [rng.gauss(0, 1) for _ in range(30)]
    shifted = [rng.gauss(1, 1) for _ in range(30)]  # a one-sigma shift
    points = ewma_chart(in_control + shifted, target=0, sigma=1)
    assert not any(p.out_of_control for p in points[:30])
    assert any(p.out_of_control for p in points[30:])
    # A single 1-sigma point never breaks the 3-sigma rule on its own.
    assert not any(abs(v) > 3 for v in shifted[:5])


def test_ewma_rejects_bad_parameters():
    with pytest.raises(ValueError):
        ewma_chart([1], target=0, sigma=1, lam=0)
    with pytest.raises(ValueError):
        ewma_chart([1], target=0, sigma=0)


def test_capability_centered_and_off_center():
    centered = capability([9, 10, 11], lsl=7, usl=13)  # mean 10, s = 1
    assert centered.cp == pytest.approx(1)
    assert centered.cpk == pytest.approx(1)
    assert centered.ppk == pytest.approx(1)

    off = capability([10, 11, 12], lsl=7, usl=13)  # mean 11: 2 sigma from USL
    assert off.cp == pytest.approx(1)
    assert off.cpk == pytest.approx(2 / 3)


def test_capability_uses_short_term_sigma_when_given():
    result = capability([9, 10, 11], lsl=7, usl=13, sigma_within=0.5)
    assert result.cp == pytest.approx(2)
    assert result.cpk == pytest.approx(2)
    assert result.ppk == pytest.approx(1)  # Ppk still uses the overall sigma


def test_capability_one_sided():
    result = capability([9, 10, 11], lsl=None, usl=13)
    assert result.cp is None and result.pp is None
    assert result.cpk == pytest.approx(1)


def test_capability_rejects_bad_input():
    with pytest.raises(ValueError):
        capability([1, 2], lsl=None, usl=None)
    with pytest.raises(ValueError):
        capability([1, 2], lsl=3, usl=3)
    with pytest.raises(ValueError):
        capability([1], lsl=0, usl=2)
    with pytest.raises(ValueError):
        capability([1, 1], lsl=0, usl=2)
