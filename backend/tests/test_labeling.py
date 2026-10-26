import pytest
from sqlmodel import select

from app.models import AuditLog, Role
from tests.conftest import upload_csv

# One gold item (/g.png) and two regular items.
ITEMS = "image_url,gold_answer\n/g.png,cat\n/1.png,\n/2.png,\n"


@pytest.fixture
def setup(client, admin, make_project, make_user):
    """Create a project with ITEMS and return a function that adds a labeler to it."""

    def setup(**project_settings):
        project = make_project(**({"gold_rate": 0, "overlap_rate": 0} | project_settings))
        upload_csv(client, project["id"], admin, ITEMS)
        member_ids: list[int] = []

        def join() -> dict[str, str]:
            user, headers = make_user(Role.labeler)
            member_ids.append(user.id)
            client.put(
                f"/api/projects/{project['id']}/members",
                json={"user_ids": member_ids},
                headers=admin,
            )
            return headers

        return project, join

    return setup


def next_task(client, project, headers):
    return client.get(f"/api/projects/{project['id']}/queue/next", headers=headers)


def submit(client, task, headers, value="cat", time_spent_ms=1200):
    return client.post(
        f"/api/assignments/{task['assignment_id']}/label",
        json={"value": value, "time_spent_ms": time_spent_ms},
        headers=headers,
    )


def label_all(client, project, headers, value="cat") -> list[str]:
    """Label until the queue is empty; return the image URLs seen, in order."""
    seen = []
    while (response := next_task(client, project, headers)).status_code == 200:
        task = response.json()
        seen.append(task["item"]["payload"]["image_url"])
        assert submit(client, task, headers, value=value).status_code == 201
    assert response.status_code == 204
    return seen


def test_labeler_works_through_regular_items_until_empty(client, setup):
    project, join = setup()
    headers = join()

    first = next_task(client, project, headers).json()
    assert first["label_options"] == ["cat", "dog", "bird"]
    assert first["item"]["payload"] == {"image_url": "/1.png"}

    # With gold_rate 0 the gold item never comes up, and it doesn't keep the queue open.
    assert label_all(client, project, headers) == ["/1.png", "/2.png"]
    progress = client.get(f"/api/projects/{project['id']}/queue/progress", headers=headers)
    assert progress.json() == {"completed": 2, "remaining": 0}


def test_gold_items_are_mixed_in_at_the_gold_rate(client, setup):
    project, join = setup(gold_rate=1)
    alice, bob = join(), join()

    # A gold draw on every request: each labeler gets the gold item first (every
    # labeler may see each gold item once), then regular work.
    assert next_task(client, project, bob).json()["item"]["payload"] == {"image_url": "/g.png"}
    assert label_all(client, project, alice) == ["/g.png", "/1.png", "/2.png"]


def test_gold_answers_are_never_sent_to_labelers(client, setup):
    project, join = setup(gold_rate=1)
    task = next_task(client, project, join()).json()
    assert task["item"] == {"id": task["item"]["id"], "payload": {"image_url": "/g.png"}}


def test_regular_items_go_to_one_labeler_without_overlap(client, setup):
    project, join = setup()
    alice, bob, carol = join(), join(), join()
    a = next_task(client, project, alice).json()
    b = next_task(client, project, bob).json()
    assert a["item"]["id"] != b["item"]["id"]
    assert next_task(client, project, carol).status_code == 204


def test_overlap_items_go_to_overlap_labelers_people(client, setup):
    project, join = setup(overlap_rate=1, overlap_labelers=2)
    alice, bob, carol = join(), join(), join()

    # Started overlap items are finished first, so Bob gets the item Alice has open.
    a = next_task(client, project, alice).json()
    b = next_task(client, project, bob).json()
    assert a["item"]["id"] == b["item"]["id"]

    # Two labelers is the limit, so Carol gets the other item.
    c = next_task(client, project, carol).json()
    assert c["item"]["id"] != a["item"]["id"]


def test_asking_again_returns_the_same_open_task(client, setup):
    project, join = setup()
    headers = join()
    assert next_task(client, project, headers).json() == next_task(client, project, headers).json()


def test_label_value_must_be_a_project_option(client, setup):
    project, join = setup()
    headers = join()
    task = next_task(client, project, headers).json()
    assert submit(client, task, headers, value="horse").status_code == 422


def test_cannot_label_twice_or_label_someone_elses_task(client, setup):
    project, join = setup()
    alice, bob = join(), join()
    task = next_task(client, project, alice).json()

    assert submit(client, task, bob).status_code == 404
    assert submit(client, task, alice).status_code == 201
    assert submit(client, task, alice).status_code == 409


def test_non_members_and_non_labelers_cannot_use_the_queue(client, admin, setup, make_user):
    project, _ = setup()
    _, outsider = make_user(Role.labeler)
    assert next_task(client, project, outsider).status_code == 404
    assert next_task(client, project, admin).status_code == 403


def test_labelers_see_their_own_gold_accuracy(client, setup):
    project, join = setup(gold_rate=1)
    headers = join()
    url = f"/api/projects/{project['id']}/queue/accuracy"
    assert client.get(url, headers=headers).json() == {
        "gold_answered": 0,
        "gold_correct": 0,
        "accuracy": None,
    }

    label_all(client, project, headers, value="dog")  # wrong on the gold item
    assert client.get(url, headers=headers).json() == {
        "gold_answered": 1,
        "gold_correct": 0,
        "accuracy": 0.0,
    }


def test_each_label_is_audited(client, session, setup):
    project, join = setup()
    headers = join()
    task = next_task(client, project, headers).json()
    label = submit(client, task, headers, time_spent_ms=900).json()

    entry = session.exec(select(AuditLog).where(AuditLog.action == "label.create")).one()
    assert entry.target_id == label["id"]
    assert entry.after == {"item_id": task["item"]["id"], "value": "cat", "time_spent_ms": 900}
