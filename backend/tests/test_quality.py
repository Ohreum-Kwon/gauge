from datetime import UTC, datetime, timedelta

import pytest

from app.models import Project, Role, User
from app.services.quality import LabelRow, agreement, labeler_chart, labeler_quality
from app.stats import Rule
from tests.conftest import upload_csv

DAY_1 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PROJECT = Project(name="p", target_error_rate=0.1, overlap_labelers=3, label_options=["a", "b"])
LABELER = User(id=1, email="l@x.dev", role=Role.labeler, password_hash="")


def gold_day(day: int, answered: int, wrong: int, user_id: int = 1) -> list[LabelRow]:
    """`answered` gold labels on day `day` (1-based), the first `wrong` of them wrong."""
    at = DAY_1 + timedelta(days=day - 1)
    return [
        LabelRow(
            user_id=user_id,
            item_id=1000 * day + i,
            value="b" if i < wrong else "a",
            gold_answer="a",
            created_at=at + timedelta(minutes=i),
            time_spent_ms=2000,
        )
        for i in range(answered)
    ]


def test_chart_has_one_point_per_day_of_gold_answers():
    rows = gold_day(1, 20, 2) + gold_day(2, 25, 5)
    chart = labeler_chart(PROJECT, rows)

    assert [d.day.isoformat() for d in chart.days] == ["2026-10-01", "2026-10-02"]
    assert [(d.point.defects, d.point.size) for d in chart.days] == [(2, 20), (5, 25)]
    assert chart.center == 0.1
    assert chart.alerts == []


def test_drift_raises_an_alert_on_the_day_it_happens():
    # Five good days around the 10% target, then a day at 50% errors.
    rows = [r for day in range(1, 6) for r in gold_day(day, 20, 2)] + gold_day(6, 20, 10)
    quality = labeler_quality(PROJECT, LABELER, rows)

    assert quality.status == "out_of_control"
    assert quality.latest_alert.day.isoformat() == "2026-10-06"
    assert quality.latest_alert.violation.rule == Rule.beyond_3_sigma
    assert quality.gold_answered == 120
    assert quality.accuracy == pytest.approx(1 - 20 / 120)


def test_good_labeler_is_in_control_and_new_labeler_has_too_little_data():
    steady = [r for day in range(1, 6) for r in gold_day(day, 20, 2)]
    assert labeler_quality(PROJECT, LABELER, steady).status == "in_control"
    assert labeler_quality(PROJECT, LABELER, gold_day(1, 5, 0)).status == "insufficient_data"
    assert labeler_quality(PROJECT, LABELER, []).accuracy is None


def test_an_old_alert_no_longer_flags_a_labeler_who_recovered():
    rows = gold_day(1, 20, 12) + [r for day in range(2, 6) for r in gold_day(day, 20, 2)]
    quality = labeler_quality(PROJECT, LABELER, rows)
    assert quality.latest_alert.day.isoformat() == "2026-10-01"
    assert quality.status == "in_control"


def test_speed_stats():
    rows = [LabelRow(1, i, "a", None, DAY_1, ms) for i, ms in enumerate([300, 500, 2000, 4000])]
    quality = labeler_quality(PROJECT, LABELER, rows)
    assert quality.median_time_ms == 1250
    assert quality.fast_share == 0.5


def test_agreement_uses_regular_items_labeled_by_several_people():
    def row(user, item, value, gold=None):
        return LabelRow(user, item, value, gold, DAY_1, 1000)

    rows = [
        # Item 1: three labelers agree. Item 2: two of three agree.
        row(1, 1, "a"), row(2, 1, "a"), row(3, 1, "a"),
        row(1, 2, "a"), row(2, 2, "b"), row(3, 2, "a"),
        # Item 3: only two labels so far, so pairwise kappa uses it but Fleiss doesn't.
        row(1, 3, "b"), row(2, 3, "b"),
        # Gold and single-labeled items don't count toward agreement.
        row(1, 4, "a", gold="a"), row(2, 4, "a", gold="a"), row(3, 5, "b"),
    ]  # fmt: skip
    result = agreement(PROJECT, rows)

    assert result.overlap_items == 2
    assert result.raters_per_item == 3
    assert result.fleiss_kappa is not None
    assert [(p.user_a, p.user_b, p.shared_items) for p in result.pairs] == [
        (1, 2, 3),
        (1, 3, 2),
        (2, 3, 2),
    ]


def test_quality_api(client, admin, make_project, make_user):
    project = make_project(gold_rate=1, overlap_rate=0)
    upload_csv(client, project["id"], admin, "image_url,gold_answer\n/g.png,cat\n/1.png,\n")
    labeler, headers = make_user(Role.labeler)
    reviewer, reviewer_headers = make_user(Role.reviewer)
    client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_ids": [labeler.id, reviewer.id]},
        headers=admin,
    )
    task = client.get(f"/api/projects/{project['id']}/queue/next", headers=headers).json()
    client.post(
        f"/api/assignments/{task['assignment_id']}/label",
        json={"value": "dog", "time_spent_ms": 800},
        headers=headers,
    )

    url = f"/api/projects/{project['id']}/quality"
    assert client.get(url, headers=headers).status_code == 403
    body = client.get(url, headers=reviewer_headers).json()
    assert body["target_error_rate"] == 0.1
    [row] = body["labelers"]
    assert row["email"] == labeler.email
    assert (row["gold_answered"], row["gold_correct"], row["status"]) == (
        1,
        0,
        "insufficient_data",
    )

    chart = client.get(f"{url}/labelers/{labeler.id}/chart", headers=admin).json()
    assert chart["center"] == 0.1
    [point] = chart["points"]
    assert (point["gold_answered"], point["errors"], point["error_rate"]) == (1, 1, 1.0)
    assert client.get(f"{url}/labelers/999999/chart", headers=admin).status_code == 404
