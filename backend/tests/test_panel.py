import pytest
from sqlmodel import Session, select

from app.models import PanelMeasurement
from app.panel import (
    D65_XY,
    METRICS,
    delta_e_2000,
    fit_gamma,
    luminance_uniformity,
    white_point_delta_e,
)


# Test pairs from Sharma, Wu and Dalal (2005), Table 1, which exercise the formula's
# hue-angle edge cases.
@pytest.mark.parametrize(
    ("lab1", "lab2", "expected"),
    [
        ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
        ((50, 0, 0), (50, -1, 2), 2.3669),
        ((50, 2.49, -0.001), (50, -2.49, 0.0009), 7.1792),
        ((50, 2.5, 0), (73, 25, -18), 27.1492),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ((22.7233, 20.0904, -46.694), (23.0331, 14.973, -42.5619), 2.0373),
    ],
)
def test_delta_e_2000_matches_sharma(lab1, lab2, expected):
    assert delta_e_2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)
    assert delta_e_2000(lab2, lab1) == pytest.approx(expected, abs=1e-4)


def test_white_point_delta_e():
    assert white_point_delta_e(*D65_XY) == pytest.approx(0, abs=1e-9)
    # A warmer (more yellow) white is further off the further it moves.
    slight = white_point_delta_e(0.3157, 0.3320)
    strong = white_point_delta_e(0.3227, 0.3390)
    assert 0 < slight < strong


def test_luminance_uniformity():
    assert luminance_uniformity([350] * 9) == 100
    assert luminance_uniformity([300, 350, 350, 350, 400, 350, 350, 350, 350]) == 75
    with pytest.raises(ValueError):
        luminance_uniformity([])
    with pytest.raises(ValueError):
        luminance_uniformity([0, 0])


def test_fit_gamma_recovers_the_exponent():
    levels = [0, 32, 64, 96, 128, 160, 192, 224, 255]
    black, white = 0.3, 350.0
    for gamma in (1.8, 2.2, 2.4):
        lums = [black + (white - black) * (v / 255) ** gamma for v in levels]
        assert fit_gamma(levels, lums) == pytest.approx(gamma)


def test_fit_gamma_rejects_incomplete_ramps():
    with pytest.raises(ValueError):
        fit_gamma([32, 255], [10, 350])
    with pytest.raises(ValueError):
        fit_gamma([0, 255], [0.3, 350])
    with pytest.raises(ValueError):
        fit_gamma([0, 128, 255], [5, 5, 5])


def test_every_metric_target_is_inside_its_spec():
    for metric in METRICS.values():
        assert metric.lsl is not None or metric.usl is not None, metric.key
        assert metric.lsl is None or metric.lsl < metric.target, metric.key
        assert metric.usl is None or metric.target < metric.usl, metric.key


def test_panel_measurement_round_trip(session: Session):
    session.add(
        PanelMeasurement(
            line="L1",
            lot="T-0042",
            panel_serial="P000001",
            subgroup=0,
            metric="tft_vth",
            value=1.02,
        )
    )
    session.commit()
    row = session.exec(select(PanelMeasurement)).one()
    assert row.metric in METRICS
    assert row.value == pytest.approx(1.02)
    assert row.measured_at is not None
