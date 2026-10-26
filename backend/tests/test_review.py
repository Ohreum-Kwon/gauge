import csv
import io

import pytest
from sqlmodel import select

from app.models import AuditLog, Role
from app.services.quality import LabelRow
from app.services.review import Reason, ReviewLabel, _majority, _regular_labels, _review_reasons
from tests.conftest import upload_csv
from tests.test_quality import DAY_1, PROJECT, gold_day


def test_majority_ignores_flagged_labels_and_ties():
    def label(value, flagged=False):
        return ReviewLabel(1, value, flagged)

    assert _majority([label("a"), label("a"), label("b")]) == "a"
    assert _majority([label("a"), label("b")]) is None
    assert _majority([label("a"), label("b", flagged=True)]) == "a"
    assert _majority([label("a", flagged=True)]) is None
    assert _majority([]) is None


def test_items_go_to_review_only_when_trusted_labels_do_not_settle_them():
    trusted, flagged = ReviewLabel(1, "a", False), ReviewLabel(2, "b", True)
    # A flagged labeler disagreeing with a trusted one doesn't need a person.
    assert _review_reasons([trusted, flagged]) == []
    assert _review_reasons([trusted]) == []
    # Only untrusted labels, or a tie among trusted ones, does.
    assert _review_reasons([flagged]) == [Reason.flagged_labeler]
    assert _review_reasons([trusted, ReviewLabel(3, "c", False), flagged]) == [
        Reason.disagreement,
        Reason.flagged_labeler,
    ]


def test_labels_on_out_of_control_days_are_flagged():
    # Labeler 1 gets 12 of 20 gold wrong on day 1 (far above the 10% target), and is
    # fine on day 2. Their regular labels on day 1 are flagged; day 2's are not.
    rows = gold_day(1, 20, 12) + gold_day(2, 20, 2)
    rows += [
        LabelRow(1, 500, "a", None, DAY_1, 1000),
        LabelRow(1, 501, "a", None, rows[-1].created_at, 1000),
        LabelRow(2, 500, "b", None, DAY_1, 1000),
    ]
    labels = _regular_labels(PROJECT, rows)
    assert labels[500] == [ReviewLabel(1, "a", True), ReviewLabel(2, "b", False)]
    assert labels[501] == [ReviewLabel(1, "a", False)]


@pytest.fixture
def disagreement(client, admin, make_project, make_user):
    """Two labelers label the same overlap item differently."""
    project = make_project(gold_rate=0, overlap_rate=1, overlap_labelers=2)
    upload_csv(client, project["id"], admin, "image_url,gold_answer\n/1.png,\n")
    users = [make_user(Role.labeler) for _ in range(2)]
    reviewer, reviewer_headers = make_user(Role.reviewer)
    client.put(
        f"/api/projects/{project['id']}/members",
        json={"user_ids": [u.id for u, _ in users] + [reviewer.id]},
        headers=admin,
    )
    for (_, headers), value in zip(users, ["cat", "dog"], strict=True):
        task = client.get(f"/api/projects/{project['id']}/queue/next", headers=headers).json()
        client.post(
            f"/api/assignments/{task['assignment_id']}/label",
            json={"value": value, "time_spent_ms": 1500},
            headers=headers,
        )
    return project, reviewer_headers, users


def test_disagreements_reach_the_review_queue_until_resolved(client, session, disagreement):
    project, reviewer, _ = disagreement
    url = f"/api/projects/{project['id']}/review"

    queue = client.get(url, headers=reviewer).json()
    assert queue["total"] == 1
    [item] = queue["items"]
    assert item["reasons"] == ["disagreement"]
    assert sorted(lab["value"] for lab in item["labels"]) == ["cat", "dog"]

    resolve = f"/api/projects/{project['id']}/items/{item['id']}/resolution"
    assert client.put(resolve, json={"value": "horse"}, headers=reviewer).status_code == 422
    assert client.put(resolve, json={"value": "cat"}, headers=reviewer).status_code == 200
    assert client.get(url, headers=reviewer).json() == {"total": 0, "items": []}

    # Changing a resolution is allowed, and the audit log keeps both versions.
    client.put(resolve, json={"value": "dog", "note": "tail"}, headers=reviewer)
    entries = session.exec(
        select(AuditLog).where(AuditLog.action == "item.resolve").order_by(AuditLog.id)
    ).all()
    assert [(e.before, e.after["value"]) for e in entries] == [
        (None, "cat"),
        ({"value": "cat", "note": None}, "dog"),
    ]


def test_labelers_cannot_see_the_review_queue(client, disagreement):
    project, _, users = disagreement
    labeler = users[0][1]
    assert client.get(f"/api/projects/{project['id']}/review", headers=labeler).status_code == 403


def test_export_uses_resolutions_and_marks_ties_unresolved(client, admin, disagreement):
    project, reviewer, _ = disagreement
    url = f"/api/projects/{project['id']}/export.csv"

    def export():
        response = client.get(url, headers=admin)
        assert response.headers["content-type"].startswith("text/csv")
        return list(csv.DictReader(io.StringIO(response.text)))

    [row] = export()
    assert (row["image_url"], row["final_label"], row["source"], row["labels"]) == (
        "/1.png",
        "",
        "unresolved",
        "2",
    )
    client.put(
        f"/api/projects/{project['id']}/items/{row['item_id']}/resolution",
        json={"value": "dog"},
        headers=reviewer,
    )
    [row] = export()
    assert (row["final_label"], row["source"]) == ("dog", "resolution")


def test_audit_log_lists_changes_newest_first(client, admin, disagreement, make_user):
    _, labeler = make_user(Role.labeler)
    assert client.get("/api/audit", headers=labeler).status_code == 403

    page = client.get("/api/audit", headers=admin).json()
    assert page["entries"][0]["action"] == "label.create"
    assert page["entries"][-1]["action"] == "project.create"
    assert page["total"] == len(page["entries"])

    labels = client.get("/api/audit?action=label.create&limit=1", headers=admin).json()
    assert labels["total"] == 2
    assert len(labels["entries"]) == 1
    assert labels["entries"][0]["actor_email"].startswith("labeler")
