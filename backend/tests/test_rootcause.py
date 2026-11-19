"""Root-cause ranking: worked examples for each kind of cause, and the API."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Role
from app.rootcause import CauseKind, Event, Observation, analyze, run_start, shift_of
from tests.conftest import upload_csv

DAY_1 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CLASSES = ["cat", "dog", "truck", "ship", "bird", "frog", "deer", "horse", "plane", "car"]


def answers(day: int, n: int, wrong: int, classes=CLASSES, hour: int = 9) -> list[Observation]:
    """`n` answers on `day`, cycling through `classes`; the first `wrong` are defects."""
    at = DAY_1.replace(hour=hour) + timedelta(days=day - 1)
    return [
        Observation(at + timedelta(minutes=i), i < wrong, {"class": classes[i % len(classes)]})
        for i in range(n)
    ]


def chart(obs: list[Observation], center: float = 0.1):
    """Days and z-scores of a p-chart of `obs`, for `analyze`."""
    days = sorted({o.day for o in obs})
    z = []
    for d in days:
        today = [o for o in obs if o.day == d]
        p = sum(o.defect for o in today) / len(today)
        z.append((p - center) / (center * (1 - center) / len(today)) ** 0.5)
    return days, z


def test_the_run_starts_at_the_first_point_above_center_before_the_alert():
    days = [DAY_1.date() + timedelta(days=i) for i in range(6)]
    assert run_start(days, [-1, 0.5, -0.2, 0.4, 2.0, 3.5], days[5]) == days[3]
    assert run_start(days, [1, 1, 1, 1, 1, 4], days[5]) == days[0]


def drift_week(broken=None) -> list[Observation]:
    """Five days at 5% errors, then three at about 40%. With `broken`, the extra errors
    all fall on those classes; otherwise they're spread over every class."""
    obs = [o for day in range(1, 6) for o in answers(day, 60, 3)]
    for day in (6, 7, 8):
        if broken:
            # Every answer on a broken class is wrong; the rest stay at 5%.
            at = DAY_1 + timedelta(days=day - 1)
            for i in range(60):
                cls = CLASSES[i % 10]
                wrong = cls in broken or i % 20 == 0
                obs.append(Observation(at + timedelta(minutes=i), wrong, {"class": cls}))
        else:
            obs += answers(day, 60, 24)
    return obs


def test_a_change_at_the_onset_ranks_first():
    obs = drift_week(broken={"cat", "dog", "truck"})
    days, z = chart(obs)
    update = Event("model_update", "judge updated from v1 to v2", DAY_1 + timedelta(days=5))
    result = analyze(obs, days, z, days[-1], 0.1, events=[update], dimensions={"class": "class"})

    assert result.run_start == days[5]
    assert result.compared_with == "baseline"
    top, second = result.causes[:2]
    assert top.kind == CauseKind.event and top.score == pytest.approx(1.0)
    assert "the day the shift began" in top.explanation
    assert second.kind == CauseKind.concentration
    assert set(second.evidence["values"]) == {"cat", "dog", "truck"}
    assert second.evidence["share_of_answers"] == pytest.approx(0.3, abs=0.01)
    assert second.score > 0.6


def test_an_old_or_later_event_is_not_blamed():
    obs = drift_week()
    days, z = chart(obs)
    old = Event("guideline_change", "old edit", DAY_1)
    later = Event("guideline_change", "after the alert", DAY_1 + timedelta(days=9))
    assert analyze(obs, days, z, days[-1], 0.1, events=[old, later]).causes == []


def test_errors_spread_evenly_are_not_a_concentration():
    obs = drift_week()
    days, z = chart(obs)
    result = analyze(obs, days, z, days[-1], 0.1, dimensions={"class": "class"})
    assert [c for c in result.causes if c.kind == CauseKind.concentration] == []


def test_only_this_labeler_changed():
    obs = drift_week()
    days, z = chart(obs)
    steady = {f"peer{p}": [o for d in range(1, 9) for o in answers(d, 40, 4)] for p in range(3)}
    result = analyze(obs, days, z, days[-1], 0.1, peers=steady, subject="ann@x.dev")
    cause = result.causes[0]
    assert cause.kind == CauseKind.labeler and cause.title == "Only ann@x.dev changed"
    assert cause.score == pytest.approx(1.0)


def test_when_everyone_changed_it_is_not_this_labeler():
    obs = drift_week()
    days, z = chart(obs)
    peers = {f"peer{p}": drift_week() for p in range(3)}
    result = analyze(obs, days, z, days[-1], 0.1, peers=peers)
    assert [c for c in result.causes if c.kind == CauseKind.labeler] == []


def test_bad_from_day_one_is_compared_with_the_center_and_the_typical_peer():
    obs = [o for d in range(1, 4) for o in answers(d, 40, 30)]
    days, z = chart(obs)
    # One awful peer doesn't make the typical peer look awful.
    peers = {
        "good1": [o for d in range(1, 4) for o in answers(d, 40, 4)],
        "good2": [o for d in range(1, 4) for o in answers(d, 40, 4)],
        "awful": [o for d in range(1, 4) for o in answers(d, 40, 40)],
    }
    result = analyze(obs, days, z, days[-1], 0.1, peers=peers, subject="ann@x.dev")
    assert result.compared_with == "center"
    assert result.run_start == days[0]
    cause = result.causes[0]
    assert cause.kind == CauseKind.labeler
    assert cause.evidence["median_peer_rate"] == pytest.approx(0.1)
    assert cause.score == pytest.approx(1.0)


def test_shifts():
    assert shift_of(DAY_1.replace(hour=3)).startswith("night")
    assert shift_of(DAY_1.replace(hour=9)).startswith("day")
    assert shift_of(DAY_1.replace(hour=20)).startswith("evening")


def test_a_bad_night_shift_is_a_concentration():
    obs = []
    for day in range(1, 9):
        bad = day >= 6
        obs += [
            Observation(o.at, o.defect, {"shift": shift_of(o.at)})
            for o in answers(day, 30, 2, hour=10)
        ]
        obs += [
            Observation(o.at, o.defect, {"shift": shift_of(o.at)})
            for o in answers(day, 30, 20 if bad else 2, hour=2)
        ]
    days, z = chart(obs)
    result = analyze(obs, days, z, days[-1], 0.1, dimensions={"shift": "shift"})
    cause = result.causes[0]
    assert cause.kind == CauseKind.concentration
    assert cause.evidence["values"] == ["night (00-08 UTC)"]


@pytest.fixture
def bad_labeler(client, admin, make_project, make_user):
    """A labeler who gets every gold question wrong for two days."""
    project = make_project(gold_rate=1)
    rows = "".join(f"/{i}.png,cat\n" for i in range(30)) + "/r.png,\n"
    upload_csv(client, project["id"], admin, "image_url,gold_answer\n" + rows)
    user, headers = make_user(Role.labeler)
    client.put(
        f"/api/projects/{project['id']}/members", json={"user_ids": [user.id]}, headers=admin
    )
    for _ in range(25):
        task = client.get(f"/api/projects/{project['id']}/queue/next", headers=headers).json()
        response = client.post(
            f"/api/assignments/{task['assignment_id']}/label",
            json={"value": "dog", "time_spent_ms": 2000},
            headers=headers,
        )
        assert response.status_code == 201, response.text
    return project, user


def test_root_cause_endpoint(client, admin, bad_labeler):
    project, user = bad_labeler
    base = f"/api/projects/{project['id']}"
    chart_data = client.get(f"{base}/quality/labelers/{user.id}/chart", headers=admin).json()
    day = chart_data["alerts"][-1]["day"]

    response = client.get(f"{base}/quality/labelers/{user.id}/root-cause?day={day}", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["compared_with"] == "center"
    assert body["run_rate"] == 1.0
    # The only batch came before any labels, so there's nothing to compare it with, and
    # with no peers and one class there's no other candidate either.
    assert body["causes"] == []

    missing = client.get(
        f"{base}/quality/labelers/{user.id}/root-cause?day=2020-01-01", headers=admin
    )
    assert missing.status_code == 404
    agreement = client.get(
        f"{base}/quality/labelers/{user.id}/root-cause?day={day}&chart=agreement", headers=admin
    )
    assert agreement.status_code == 404


def test_admins_log_guideline_changes_and_staff_read_them(client, admin, make_project, make_user):
    project = make_project()
    url = f"/api/projects/{project['id']}/events"
    _, labeler = make_user(Role.labeler)
    body = {"description": "Pickups count as trucks", "occurred_at": "2026-10-03T00:00:00Z"}
    assert client.post(url, json=body, headers=labeler).status_code in (403, 404)
    created = client.post(url, json=body, headers=admin)
    assert created.status_code == 201
    assert created.json()["kind"] == "guideline_change"

    _, reviewer = make_user(Role.reviewer)
    client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_ids": [client.get("/api/auth/me", headers=reviewer).json()["id"]]},
        headers=admin,
    )
    events = client.get(url, headers=reviewer).json()
    assert [e["description"] for e in events] == ["Pickups count as trucks"]
