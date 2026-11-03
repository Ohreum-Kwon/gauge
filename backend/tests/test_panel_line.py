import random
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app import panel_sim
from app.models import PanelMeasurement, Role
from app.panel import METRICS
from app.services import panel_line
from app.services.panel_line import BASELINE_SUBGROUPS, Subgroup, metric_chart

VTH = METRICS["tft_vth"]
AT = datetime(2026, 11, 1, tzinfo=UTC)


def series(means: list[float], seed: int = 3) -> list[Subgroup]:
    rng = random.Random(seed)
    return [
        Subgroup(i, AT, "T-1", [rng.gauss(mean, 0.03) for _ in range(5)])
        for i, mean in enumerate(means)
    ]


def test_needs_a_complete_baseline():
    assert metric_chart("L1", VTH, series([1.0] * BASELINE_SUBGROUPS)) is None
    assert metric_chart("L1", VTH, series([1.0] * (BASELINE_SUBGROUPS + 1))) is not None


def test_step_shift_alarms_where_it_starts():
    chart = metric_chart("L1", VTH, series([1.0] * 30 + [1.08] * 10))
    assert chart.status == "out_of_control"
    alarm = chart.first("alarm")
    assert (alarm.subgroup, alarm.rule, alarm.above) == (30, "beyond_3_sigma", True)
    assert chart.recent_capability.mean == pytest.approx(1.08, abs=0.02)


def fixed_spread(means: list[float]) -> list[Subgroup]:
    """Subgroups with an exact range of 0.06, so sigma_xbar is 0.577 * 0.06 / 3 = 0.0115."""
    return [
        Subgroup(i, AT, "T-1", [m - 0.03, m - 0.015, m, m + 0.015, m + 0.03])
        for i, m in enumerate(means)
    ]


def test_zone_rules_alone_only_warn():
    # A shift of about 1.5 standard errors: zone-rule territory, never beyond 3 sigma.
    baseline = [1.0 + (0.002 if i % 2 else -0.002) for i in range(BASELINE_SUBGROUPS)]
    chart = metric_chart("L1", VTH, fixed_spread(baseline + [1.017] * 10))
    assert chart.first("alarm") is None
    assert chart.status == "warning"
    assert {s.severity for s in chart.monitored_signals} == {"warning"}


def test_baseline_signals_do_not_set_the_status():
    means = [1.0] * BASELINE_SUBGROUPS + [1.0] * 10
    means[5] = 1.2  # an outlier inside the baseline
    chart = metric_chart("L1", VTH, series(means))
    assert any(s.subgroup == 5 for s in chart.signals)
    assert chart.status == "in_control"


@pytest.fixture
def simulated(session: Session) -> Session:
    panel_sim.simulate(session)
    return session


def test_simulation_tells_the_documented_story(simulated: Session):
    charts = {(c.line, c.metric.key): c for c in panel_line.all_charts(simulated)}
    assert len(charts) == 2 * len(METRICS)

    day = panel_sim.PERIODS_PER_DAY
    drifting = {
        ("L2", "white_luminance"): range(4 * day, 5 * day),  # alarms on day 5
        ("L2", "luminance_uniformity"): range(4 * day, 5 * day),
        ("L1", "tft_vth"): [5 * day],  # alarms at the first subgroup of day 6
        ("L1", "tft_ion"): [5 * day],
    }
    for key, alarm_window in drifting.items():
        chart = charts[key]
        assert chart.status == "out_of_control", key
        assert chart.first("alarm").subgroup in alarm_window, key
        # Backlight aging dims the panel; the shifted lot runs high Vth and low Ion.
        assert chart.first("alarm").above == (key[1] == "tft_vth"), key

    for key, chart in charts.items():
        if key not in drifting:
            assert chart.status == "in_control", (key, chart.monitored_signals)

    # The aging backlight is still mostly inside spec, but its margin has collapsed.
    luminance = charts[("L2", "white_luminance")]
    assert luminance.baseline_capability.cpk > 1.33 > luminance.recent_capability.cpk


def test_simulation_is_idempotent_and_resettable(simulated: Session):
    def count() -> int:
        return simulated.exec(select(func.count()).select_from(PanelMeasurement)).one()

    assert count() == panel_sim.expected_rows()
    panel_sim.simulate(simulated)
    assert count() == panel_sim.expected_rows()
    panel_sim.simulate(simulated, reset=True)
    assert count() == panel_sim.expected_rows()


def test_summary_api(client: TestClient, simulated: Session, admin):
    body = client.get("/api/panel-line", headers=admin).json()
    assert body["lines"] == ["L1", "L2"]
    assert body["baseline_subgroups"] == BASELINE_SUBGROUPS
    assert [m["key"] for m in body["metrics"]] == list(METRICS)
    by_key = {(s["line"], s["metric"]): s for s in body["series"]}
    vth = by_key[("L1", "tft_vth")]
    assert vth["status"] == "out_of_control"
    assert vth["first_alarm"]["rule"] == "beyond_3_sigma"
    assert by_key[("L2", "tft_vth")]["first_alarm"] is None


def test_chart_api(client: TestClient, simulated: Session, admin):
    body = client.get("/api/panel-line/lines/L1/metrics/tft_vth", headers=admin).json()
    assert body["metric"]["unit"] == "V"
    assert body["subgroup_size"] == panel_sim.PANELS_PER_SUBGROUP
    assert len(body["points"]) == panel_sim.SUBGROUPS
    assert body["points"][40]["lot"] == panel_sim.SHIFTED_LOT
    assert body["xbar_lcl"] < body["center"] < body["xbar_ucl"]
    assert body["recent_capability"]["cp"] is not None


def test_chart_api_errors(client: TestClient, simulated: Session, admin):
    assert client.get("/api/panel-line/lines/L1/metrics/nope", headers=admin).status_code == 404
    assert client.get("/api/panel-line/lines/L9/metrics/gamma", headers=admin).status_code == 404


def test_panel_line_is_staff_only(client: TestClient, make_user):
    _, labeler = make_user(Role.labeler)
    _, reviewer = make_user(Role.reviewer)
    assert client.get("/api/panel-line", headers=labeler).status_code == 403
    assert client.get("/api/panel-line", headers=reviewer).status_code == 200
    assert client.get("/api/panel-line").status_code == 401
