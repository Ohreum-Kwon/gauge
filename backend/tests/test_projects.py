from sqlmodel import select

from app.models import AuditLog, Role
from tests.conftest import upload_csv


def test_admin_creates_project_and_it_is_audited(client, session, make_project):
    project = make_project(name="Pets")

    assert project["name"] == "Pets"
    assert project["label_options"] == ["cat", "dog", "bird"]
    entry = session.exec(select(AuditLog).where(AuditLog.action == "project.create")).one()
    assert entry.target_id == project["id"]


def test_label_options_must_be_unique(client, admin):
    body = {"name": "x", "task_type": "image_classification", "label_options": ["a", "a"]}
    assert client.post("/api/projects", json=body, headers=admin).status_code == 422


def test_non_admins_cannot_create_projects(client, make_user):
    _, labeler = make_user(Role.labeler)
    body = {"name": "x", "task_type": "image_classification", "label_options": ["a", "b"]}
    assert client.post("/api/projects", json=body, headers=labeler).status_code == 403


def test_labelers_see_only_projects_they_belong_to(client, admin, make_user, make_project):
    mine, other = make_project(name="Mine"), make_project(name="Other")
    labeler, headers = make_user(Role.labeler)
    client.put(
        f"/api/projects/{mine['id']}/members", json={"user_ids": [labeler.id]}, headers=admin
    )

    listed = client.get("/api/projects", headers=headers).json()
    assert [p["name"] for p in listed] == ["Mine"]
    assert client.get(f"/api/projects/{other['id']}", headers=headers).status_code == 404


def test_admins_cannot_be_project_members(client, admin, make_user, make_project):
    project = make_project()
    other_admin, _ = make_user(Role.admin)
    response = client.put(
        f"/api/projects/{project['id']}/members", json={"user_ids": [other_admin.id]}, headers=admin
    )
    assert response.status_code == 422


def test_upload_csv_counts_gold_items(client, admin, make_project):
    project = make_project()
    csv_text = "image_url,gold_answer\n/img/1.png,cat\n/img/2.png,\nhttps://x.test/3.png,dog\n"

    response = upload_csv(client, project["id"], admin, csv_text)
    assert response.status_code == 201
    assert response.json() == {"created": 3, "gold": 2}

    summary = client.get(f"/api/projects/{project['id']}", headers=admin).json()
    assert summary["item_count"] == 3
    assert summary["gold_item_count"] == 2


def test_upload_json(client, admin, make_project):
    project = make_project()
    response = client.post(
        f"/api/projects/{project['id']}/items",
        files={"file": ("items.json", b'[{"image_url": "/a.png", "gold_answer": "bird"}]')},
        headers=admin,
    )
    assert response.json() == {"created": 1, "gold": 1}


def test_bad_upload_names_the_row_and_writes_nothing(client, admin, make_project):
    project = make_project()
    csv_text = "image_url,gold_answer\n/img/1.png,cat\n/img/2.png,horse\n"

    response = upload_csv(client, project["id"], admin, csv_text)
    assert response.status_code == 422
    assert "Row 2" in response.json()["detail"]
    summary = client.get(f"/api/projects/{project['id']}", headers=admin).json()
    assert summary["item_count"] == 0


def test_items_list_shows_gold_answers_to_admins_only(client, admin, make_user, make_project):
    project = make_project()
    upload_csv(client, project["id"], admin, "image_url,gold_answer\n/img/1.png,cat\n")
    labeler, headers = make_user(Role.labeler)
    client.put(
        f"/api/projects/{project['id']}/members", json={"user_ids": [labeler.id]}, headers=admin
    )

    items = client.get(f"/api/projects/{project['id']}/items", headers=admin).json()
    assert items[0]["gold_answer"] == "cat"
    assert client.get(f"/api/projects/{project['id']}/items", headers=headers).status_code == 403
