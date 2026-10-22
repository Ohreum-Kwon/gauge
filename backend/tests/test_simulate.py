"""The demo's headline claim, tested end to end: simulate a week of labeling and check
that each labeler's control chart says what the README says it does.

Takes a minute or two, so it's marked slow: run with `pytest -m slow`. It commits for
real instead of using the rolled-back test transaction, because thousands of savepoints
in one Postgres transaction slow it to a crawl, and resets the schema afterwards.
"""

import csv

import pytest
from sqlmodel import Session, SQLModel

from app import simulate
from app.models import Role, User
from app.security import hash_password
from app.services import quality


@pytest.fixture
def committing_session(engine):
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


@pytest.mark.slow
def test_simulation_flags_the_drifter_on_day_6(committing_session, tmp_path, monkeypatch):
    session = committing_session
    sample = tmp_path / "sample.csv"
    with sample.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image_url", "gold_answer", "true_label"])
        writer.writeheader()
        for i in range(300):
            truth = simulate.CIFAR_CLASSES[i % 10]
            writer.writerow(
                {"image_url": f"/cifar/{i:05d}.png", "gold_answer": "", "true_label": truth}
            )
    monkeypatch.setattr(simulate, "CIFAR_CSV", sample)
    session.add(User(email="admin@example.com", password_hash=hash_password("x"), role=Role.admin))
    session.commit()

    project = simulate.simulate(session)
    labelers, agreement = quality.project_quality(session, project)
    by_name = {q.user.email.removeprefix("sim-").split("@")[0]: q for q in labelers}

    def alert_days(name: str) -> list[int]:
        rows = quality.load_rows(session, project, user_id=by_name[name].user.id)
        chart = quality.labeler_chart(project, rows)
        first = chart.days[0].day
        return sorted({(a.day - first).days + 1 for a in chart.alerts if a.violation.above})

    assert by_name["reliable"].status == "in_control"
    assert alert_days("reliable") == []

    assert by_name["drifter"].status == "out_of_control"
    assert alert_days("drifter")[0] == 6

    assert by_name["noisy"].status == "out_of_control"
    assert by_name["rusher"].status == "out_of_control"
    assert by_name["rusher"].fast_share > 0.9

    # The rusher agrees with nobody beyond chance; the others mostly agree.
    rusher_id = by_name["rusher"].user.id
    for pair in agreement.pairs:
        if rusher_id in (pair.user_a, pair.user_b):
            assert pair.kappa is not None and abs(pair.kappa) < 0.1
        else:
            assert pair.kappa is not None and pair.kappa > 0.4
