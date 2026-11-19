"""The LLM judge: simulated versions, the Claude provider's request, and shadow mode."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.judges import ClaudeJudge, SimulatedJudge
from app.models import EventKind, Item, Label, Project, ProjectEvent, Role
from app.services import quality, review
from app.services.judge import get_or_create_judge, items_to_judge, run_judge
from app.services.labeling import submit_label
from app.services.quality import LabelRow, judge_agreement_chart
from app.services.queue import get_or_assign_next
from tests.conftest import FixedRandom, upload_csv
from tests.test_quality import DAY_1

CLASSES = ["airplane", "automobile", "cat", "dog", "truck", "ship"]


def accuracy_by_class(judge: SimulatedJudge, n: int = 400) -> dict[str, float]:
    result = {}
    for truth in CLASSES:
        payloads = [{"image_url": f"/{truth}/{i}.png", "truth": truth} for i in range(n)]
        result[truth] = sum(judge.label(p, CLASSES) == truth for p in payloads) / n
    return result


def truth_of(payload):
    return payload.get("truth")


def test_simulated_judge_is_deterministic():
    a = SimulatedJudge("sim-judge-v1", truth_of)
    b = SimulatedJudge("sim-judge-v1", truth_of)
    payloads = [{"image_url": f"/{i}.png", "truth": CLASSES[i % 6]} for i in range(50)]
    assert [a.label(p, CLASSES) for p in payloads] == [b.label(p, CLASSES) for p in payloads]


def test_v2_quietly_breaks_three_classes():
    v1 = accuracy_by_class(SimulatedJudge("sim-judge-v1", truth_of))
    v2 = accuracy_by_class(SimulatedJudge("sim-judge-v2", truth_of))
    assert all(0.9 < acc < 0.98 for acc in v1.values())
    for broken in ("cat", "dog", "truck"):
        assert v2[broken] < 0.4
    for fine in ("airplane", "automobile", "ship"):
        assert v2[fine] > 0.9
    # The wrong answers are systematic confusions, not noise.
    judge = SimulatedJudge("sim-judge-v2", truth_of)
    wrong = {judge.label({"image_url": f"/t{i}", "truth": "truck"}, CLASSES) for i in range(50)}
    assert wrong <= {"truck", "automobile"}


def test_simulated_judge_without_truth_still_answers_an_option():
    judge = SimulatedJudge("sim-judge-v1", lambda p: None)
    assert judge.label({"image_url": "/x.png"}, CLASSES) in CLASSES
    with pytest.raises(ValueError):
        SimulatedJudge("sim-judge-v9", truth_of)


class FakeMessages:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def test_claude_judge_constrains_the_answer_to_the_options():
    messages = FakeMessages('{"label": "dog"}')
    judge = ClaudeJudge(model="claude-opus-5-5", client=SimpleNamespace(messages=messages))
    assert judge.version == "claude-opus-5-5"
    assert judge.label({"image_url": "https://example.com/a.png"}, CLASSES) == "dog"

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    schema = call["output_config"]["format"]["schema"]
    assert schema["properties"]["label"]["enum"] == CLASSES
    image = call["messages"][0]["content"][0]
    assert image["source"] == {"type": "url", "url": "https://example.com/a.png"}


def test_claude_judge_sends_site_images_inline_and_refuses_paths_outside(tmp_path, monkeypatch):
    (tmp_path / "cifar").mkdir()
    (tmp_path / "cifar" / "1.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr("app.judges.PUBLIC_DIR", tmp_path)
    messages = FakeMessages('{"label": "cat"}')
    judge = ClaudeJudge(model="m", client=SimpleNamespace(messages=messages))

    judge.label({"image_url": "/cifar/1.png"}, CLASSES)
    source = messages.calls[0]["messages"][0]["content"][0]["source"]
    assert source["type"] == "base64" and source["media_type"] == "image/png"
    with pytest.raises(FileNotFoundError):
        judge.label({"image_url": "/../secrets.png"}, CLASSES)


def test_claude_judge_reports_a_refusal():
    messages = FakeMessages("", stop_reason="refusal")
    judge = ClaudeJudge(model="m", client=SimpleNamespace(messages=messages))
    with pytest.raises(RuntimeError):
        judge.label({"image_url": "https://example.com/a.png"}, CLASSES)


class FixedJudge:
    def __init__(self, version: str, value: str):
        self.version, self.value = version, value

    def label(self, payload, options):
        return self.value


@pytest.fixture
def overlap_project(client, admin, make_project, make_user, session):
    """Three overlap items for two people, plus a judge."""
    data = make_project(gold_rate=0, overlap_rate=1, overlap_labelers=2)
    upload_csv(client, data["id"], admin, "image_url,gold_answer\n/1.png,\n/2.png,\n/3.png,\n")
    project = session.get(Project, data["id"])
    people = [make_user(Role.labeler)[0] for _ in range(2)]
    client.put(
        f"/api/projects/{project.id}/members",
        json={"user_ids": [u.id for u in people]},
        headers=admin,
    )
    judge = get_or_create_judge(session, project, "judge@example.com")
    session.commit()
    return project, people, judge


def label_next(session, project, user, value):
    assignment = get_or_assign_next(session, project, user, FixedRandom())
    return submit_label(session, assignment, user, value, 2000)


def test_judge_labels_in_shadow_without_taking_a_persons_place(session, overlap_project):
    project, (alice, bob), judge = overlap_project
    first = label_next(session, project, alice, "cat")
    assert [i.id for i, _ in items_to_judge(session, project, judge)] == [first.item_id]

    assert (
        run_judge(
            session,
            project,
            judge,
            FixedJudge("v1", "dog"),
            items_to_judge(session, project, judge),
        )
        == 1
    )
    assert items_to_judge(session, project, judge) == []
    label = session.exec(select(Label).where(Label.user_id == judge.id)).one()
    assert label.model_version == "v1" and label.value == "dog"

    # The overlap item needs two people; the judge's label doesn't count as one of them.
    second = label_next(session, project, bob, "cat")
    assert second.item_id == first.item_id


def test_a_version_change_records_a_model_update(session, overlap_project):
    project, (alice, _), judge = overlap_project
    label_next(session, project, alice, "cat")
    run_judge(
        session, project, judge, FixedJudge("v1", "cat"), items_to_judge(session, project, judge)
    )
    label_next(session, project, alice, "cat")
    run_judge(
        session, project, judge, FixedJudge("v1", "cat"), items_to_judge(session, project, judge)
    )
    assert session.exec(select(ProjectEvent)).all() == []

    label_next(session, project, alice, "dog")
    run_judge(
        session, project, judge, FixedJudge("v2", "dog"), items_to_judge(session, project, judge)
    )
    event = session.exec(select(ProjectEvent)).one()
    assert event.kind == EventKind.model_update and event.user_id == judge.id
    assert "v1 to v2" in event.description


def test_judge_labels_neither_vote_nor_count_in_fleiss(session, overlap_project):
    project, (alice, bob), judge = overlap_project
    label_next(session, project, alice, "cat")
    label_next(session, project, bob, "cat")
    run_judge(
        session, project, judge, FixedJudge("v1", "dog"), items_to_judge(session, project, judge)
    )

    final = {f.item.id: f for f in review.final_labels(session, project)}
    item = session.exec(select(Item).where(Item.project_id == project.id)).first()
    assert final[item.id].value == "cat" and final[item.id].labels == 2

    _, agreement = quality.project_quality(session, project)
    assert agreement.overlap_items == 1  # two people: complete, despite the third label
    assert any(judge.id in (p.user_a, p.user_b) for p in agreement.pairs)


def test_model_accounts_cannot_sign_in(client, session, overlap_project):
    response = client.post(
        "/api/auth/login", data={"username": "judge@example.com", "password": "!"}
    )
    assert response.status_code == 401


def test_a_persons_account_cannot_become_a_judge(session, overlap_project):
    project, (alice, _), _ = overlap_project
    with pytest.raises(ValueError):
        get_or_create_judge(session, project, alice.email)


def rows_for(user_id, day, values, item_start=0, is_model=False, version=None):
    at = DAY_1 + timedelta(days=day - 1)
    return [
        LabelRow(user_id, item_start + i, v, None, at, 0, is_model, version)
        for i, v in enumerate(values)
    ]


def test_agreement_chart_flags_a_judge_that_starts_disagreeing():
    people, judge = [], []
    for day in range(1, 7):
        start = day * 1000
        people += rows_for(1, day, ["a"] * 40, start)
        wrong = 4 if day < 5 else 20  # 10% disagreement, then 50% from day 5
        version = "v1" if day < 5 else "v2"
        judge += rows_for(9, day, ["b"] * wrong + ["a"] * (40 - wrong), start, True, version)

    chart = judge_agreement_chart(judge, people)
    assert chart.center == pytest.approx(0.1)
    assert chart.baseline_days == 3
    assert chart.reference_user_ids == [1]
    assert [d.model_version for d in chart.days] == ["v1"] * 4 + ["v2"] * 2
    assert {a.day.day for a in chart.alerts if a.violation.above} == {5, 6}


def test_agreement_chart_needs_a_baseline_and_skips_ties():
    judge = rows_for(9, 1, ["a"] * 10, 0, True, "v1")
    assert judge_agreement_chart(judge, rows_for(1, 1, ["a"] * 10)) is None
    # A tie among the reference people leaves the item out.
    tied = rows_for(1, 1, ["a"]) + rows_for(2, 1, ["b"])
    assert judge_agreement_chart(rows_for(9, 1, ["a"], 0, True), tied) is None


def test_agreement_chart_endpoint(client, admin, session, overlap_project, make_user):
    project, (alice, _), judge = overlap_project
    url = f"/api/projects/{project.id}/quality/labelers"
    assert client.get(f"{url}/{judge.id}/agreement-chart", headers=admin).json() is None
    assert client.get(f"{url}/{alice.id}/agreement-chart", headers=admin).status_code == 404

    labelers = client.get(f"/api/projects/{project.id}/quality", headers=admin).json()["labelers"]
    assert {(q["email"], q["is_model"]) for q in labelers} >= {("judge@example.com", True)}
