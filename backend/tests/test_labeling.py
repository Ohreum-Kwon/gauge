import pytest
from sqlmodel import select

from app.models import AuditLog, Role
from tests.conftest import upload_csv


@pytest.fixture
def project(client, admin, make_project):
    project = make_project()
    upload_csv(client, project["id"], admin, "image_url,gold_answer\n/1.png,cat\n/2.png,\n")
    return project


@pytest.fixture
def join(client, admin, project, make_user):
    """Create labelers and add them all to the project."""
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

    return join


def next_task(client, project, headers):
    return client.get(f"/api/projects/{project['id']}/queue/next", headers=headers)


def submit(client, task, headers, value="cat", time_spent_ms=1200):
    return client.post(
        f"/api/assignments/{task['assignment_id']}/label",
        json={"value": value, "time_spent_ms": time_spent_ms},
        headers=headers,
    )


def test_labeler_works_through_the_queue_until_empty(client, project, join):
    headers = join()

    first = next_task(client, project, headers).json()
    assert first["label_options"] == ["cat", "dog", "bird"]
    assert first["item"]["payload"] == {"image_url": "/1.png"}
    assert submit(client, first, headers).status_code == 201

    second = next_task(client, project, headers).json()
    assert second["item"]["id"] != first["item"]["id"]
    submit(client, second, headers, value="dog")

    assert next_task(client, project, headers).status_code == 204
    progress = client.get(f"/api/projects/{project['id']}/queue/progress", headers=headers)
    assert progress.json() == {"completed": 2, "remaining": 0}


def test_gold_answers_are_never_sent_to_labelers(client, project, join):
    task = next_task(client, project, join()).json()
    assert "gold_answer" not in task["item"]
    assert "cat" not in str(task["item"])


def test_asking_again_returns_the_same_open_task(client, project, join):
    headers = join()
    assert next_task(client, project, headers).json() == next_task(client, project, headers).json()


def test_two_labelers_get_different_items(client, project, join):
    alice, bob = join(), join()
    a = next_task(client, project, alice).json()
    b = next_task(client, project, bob).json()
    assert a["item"]["id"] != b["item"]["id"]


def test_label_value_must_be_a_project_option(client, project, join):
    headers = join()
    task = next_task(client, project, headers).json()
    assert submit(client, task, headers, value="horse").status_code == 422


def test_cannot_label_twice_or_label_someone_elses_task(client, project, join):
    alice, bob = join(), join()
    task = next_task(client, project, alice).json()

    assert submit(client, task, bob).status_code == 404
    assert submit(client, task, alice).status_code == 201
    assert submit(client, task, alice).status_code == 409


def test_non_members_and_non_labelers_cannot_use_the_queue(client, admin, project, make_user):
    _, outsider = make_user(Role.labeler)
    assert next_task(client, project, outsider).status_code == 404
    assert next_task(client, project, admin).status_code == 403


def test_each_label_is_audited(client, session, project, join):
    headers = join()
    task = next_task(client, project, headers).json()
    label = submit(client, task, headers, time_spent_ms=900).json()

    entry = session.exec(select(AuditLog).where(AuditLog.action == "label.create")).one()
    assert entry.target_id == label["id"]
    assert entry.after == {"item_id": task["item"]["id"], "value": "cat", "time_spent_ms": 900}
