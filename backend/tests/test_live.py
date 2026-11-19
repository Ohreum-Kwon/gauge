"""The live demo: its faults are caught, healthy charts stay quiet, and the stream and
fault endpoints work. None of this needs the database."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.live import (
    BASELINE_SAMPLES,
    GRACE_SAMPLES,
    TFT_LOT_SAMPLES,
    ChartState,
    Fault,
    LiveDemo,
)
from app.main import create_app
from app.routers import live as live_router

SEED = 7


def run(demo: LiveDemo, samples: int) -> list[dict]:
    """Step the demo and return every event it reported."""
    return [event for _ in range(samples) for event in demo.step()["events"]]


def warmed_up() -> LiveDemo:
    demo = LiveDemo(SEED)
    run(demo, BASELINE_SAMPLES + 10)
    return demo


def test_panel_charts_collect_a_baseline_before_judging():
    demo = LiveDemo(SEED)
    first = demo.step()
    assert all(p["baseline"] and p["signal"] is None for p in first["panel"])
    run(demo, BASELINE_SAMPLES)
    later = demo.step()
    assert not any(p["baseline"] for p in later["panel"])
    assert all(p["lcl"] < p["center"] < p["ucl"] for p in later["panel"])


def test_healthy_demo_is_quiet_with_this_seed():
    events = run(LiveDemo(SEED), 300)
    assert [e for e in events if e["type"] != "false_alarm"] == []


@pytest.mark.parametrize(
    ("fault", "target", "chart", "within"),
    [
        (Fault.rush, "blake", "blake", 1),
        (Fault.drift, "avery", "avery", 12),
        (Fault.tft_lot, "L1", "L1:tft_vth", 1),
        (Fault.backlight, "L1", "L1:white_luminance", 20),
        (Fault.model_update, "judge", "judge", 8),
    ],
)
def test_each_fault_is_detected_on_its_chart(fault, target, chart, within):
    demo = warmed_up()
    demo.inject(fault, target)
    events = run(demo, within)
    assert events[0] == {"type": "fault", "fault": fault.value, "target": target}
    detected = [e for e in events if e["type"] == "detected"]
    assert len(detected) == 1, events
    assert detected[0]["chart"] == chart
    assert detected[0]["fault"] == fault.value
    assert 1 <= detected[0]["samples"] <= within


def test_detection_is_reported_once_per_fault():
    demo = warmed_up()
    demo.inject(Fault.rush, "casey")
    events = run(demo, 20)
    assert sum(e["type"] == "detected" for e in events) == 1


def test_a_bad_tft_lot_runs_out():
    demo = warmed_up()
    demo.inject(Fault.tft_lot, "L1")
    events = run(demo, TFT_LOT_SAMPLES + GRACE_SAMPLES + 5)
    assert {"type": "cleared", "fault": "tft_lot", "target": "L1"} in events
    assert not any(e["type"] == "false_alarm" for e in events)
    assert demo.step()["panel"][1]["signal"] != "alarm"


def test_reset_clears_faults_without_false_alarms():
    demo = warmed_up()
    demo.inject(Fault.rush, "blake")
    demo.inject(Fault.backlight, "L1")
    run(demo, 15)
    demo.reset()
    # The luminance EWMA takes a few samples to come back; that tail isn't a false alarm.
    events = run(demo, GRACE_SAMPLES)
    assert events[0] == {"type": "reset"}
    assert not any(e["type"] in ("false_alarm", "detected") for e in events)
    assert demo.labelers["blake"].accuracy == demo.labelers["blake"].healthy


def test_an_alarm_on_a_healthy_chart_is_a_false_alarm():
    demo = LiveDemo(SEED)
    events: list[dict] = []
    demo._grade(ChartState(), "casey", "beyond_3_sigma", events)
    assert events == [
        {
            "type": "false_alarm",
            "chart": "casey",
            "rule": "beyond_3_sigma",
            "description": "One point beyond the 3-sigma limit",
        }
    ]


def test_the_model_update_alarm_is_traced_to_the_update_and_its_classes():
    demo = warmed_up()
    demo.inject(Fault.model_update, "judge")
    detected = next(e for e in run(demo, 8) if e["type"] == "detected")
    kinds = [c["kind"] for c in detected["causes"]]
    assert kinds[0] == "event"
    assert detected["causes"][0]["title"] == "Model update: judge-v1 to judge-v2"
    assert "the sample the shift began" in detected["causes"][0]["explanation"]
    assert demo.step()["labelers"][3]["version"] == "judge-v2"


def test_the_broken_classes_usually_show_up_too():
    # At detection the run is a few samples long, so the classes don't always clear
    # the bar; across visits they mostly do, and they're the right ones.
    found = 0
    for seed in range(20):
        demo = LiveDemo(seed)
        run(demo, BASELINE_SAMPLES + 10)
        demo.inject(Fault.model_update, "judge")
        detected = next(e for e in run(demo, 10) if e["type"] == "detected")
        titles = [c["title"] for c in detected["causes"] if c["kind"] == "concentration"]
        if titles:
            classes = set(titles[0].removeprefix("True class: ").split(", "))
            found += (
                classes <= {"cat", "dog", "truck"} or len(classes & {"cat", "dog", "truck"}) >= 2
            )
    assert found >= 14


def test_a_drifting_person_is_traced_to_that_person():
    demo = warmed_up()
    demo.inject(Fault.drift, "avery")
    detected = next(e for e in run(demo, 12) if e["type"] == "detected")
    assert detected["causes"][0]["kind"] == "labeler"
    assert detected["causes"][0]["title"] == "Only avery changed"


def test_reset_rolls_the_judge_back():
    demo = warmed_up()
    demo.inject(Fault.model_update, "judge")
    demo.reset()
    assert demo.labelers["judge"].version == "judge-v1"
    assert demo.labelers["judge"].fault is None


@pytest.mark.parametrize(
    ("fault", "target"),
    [
        (Fault.rush, "L1"),
        (Fault.backlight, "avery"),
        (Fault.model_update, "avery"),
        (Fault.drift, "judge"),
    ],
)
def test_faults_only_apply_to_their_kind_of_target(fault, target):
    with pytest.raises(KeyError):
        LiveDemo(SEED).inject(fault, target)


# Endpoints


@pytest.fixture
def live_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "live_seconds_per_sample", 0)
    monkeypatch.setattr(settings, "live_max_samples", 3)
    monkeypatch.setattr(settings, "live_max_sessions", 2)
    yield TestClient(create_app())
    live_router.sessions.clear()


def parse_sse(text: str) -> list[tuple[str, object]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_stream_sends_layout_history_samples_then_ends(live_client):
    with live_client.stream("GET", "/api/live/stream") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.read().decode())
    names = [name for name, _ in events]
    assert names == ["session", "history", "sample", "sample", "sample", "end"]
    session = events[0][1]
    assert session["labelers"] == ["avery", "blake", "casey"]
    assert len(events[1][1]) == BASELINE_SAMPLES + 10
    assert events[2][1]["sample"] == BASELINE_SAMPLES + 11
    # The session is gone once its stream ends.
    assert session["id"] not in live_router.sessions


def test_faults_reach_the_session(live_client):
    live_router.sessions["abc"] = demo = LiveDemo(SEED)
    response = live_client.post("/api/live/abc/faults", json={"fault": "rush", "target": "blake"})
    assert response.status_code == 204
    assert demo.labelers["blake"].fault is Fault.rush

    assert live_client.post("/api/live/abc/faults", json={"fault": "reset"}).status_code == 204
    assert demo.labelers["blake"].fault is None


def test_fault_errors(live_client):
    live_router.sessions["abc"] = LiveDemo(SEED)
    post = live_client.post
    assert post("/api/live/nope/faults", json={"fault": "reset"}).status_code == 404
    assert post("/api/live/abc/faults", json={"fault": "rush", "target": "L1"}).status_code == 422
    assert post("/api/live/abc/faults", json={"fault": "melt", "target": "L1"}).status_code == 422


def test_stream_refuses_when_full(live_client):
    live_router.sessions.update(a=LiveDemo(), b=LiveDemo())
    response = live_client.get("/api/live/stream")
    assert response.status_code == 503
