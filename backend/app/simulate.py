"""Simulate a week of labeling by four labelers with known behavior, so the quality
dashboards have a real story to show. Safe to run more than once.

    uv run python -m app.simulate            # create the project if it doesn't exist
    uv run python -m app.simulate --reset    # delete it and simulate again

The labelers:
- reliable: right 95% of the time
- noisy:    right 70% of the time
- drifter:  right 95% of the time for five days, then 60% from day 6
- rusher:   clicks the first option in about half a second, every time

It labels through the real queue and label service, so gold mixing, overlap and the
audit log behave exactly as they do for people. Timestamps are backdated over the last
DAYS days. Expected result: the drifter's control chart goes out of control on day 6,
the noisy labeler and the rusher are out of control throughout, the reliable labeler
stays in control.
"""

import argparse
import csv
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlmodel import Session, select

from app.db import get_engine
from app.models import Item, Project, ProjectMember, Role, TaskType, User
from app.security import hash_password
from app.seed import CIFAR_CLASSES, CIFAR_CSV
from app.services.labeling import submit_label
from app.services.queue import get_or_assign_next

PROJECT_NAME = "Simulated labelers (drift demo)"
DAYS = 8
LABELS_PER_DAY = 100
# Each image is reused this many times, so the queue never runs dry mid-simulation.
COPIES_PER_IMAGE = 10
GOLD_SHARE = 0.2


@dataclass(frozen=True)
class Persona:
    name: str
    # Chance of a right answer on a given (1-based) day.
    accuracy: Callable[[int], float]
    # Median seconds per label.
    median_seconds: float
    always_first_option: bool = False

    @property
    def email(self) -> str:
        return f"sim-{self.name}@gauge.dev"


PERSONAS = [
    Persona("reliable", lambda day: 0.95, median_seconds=3.5),
    Persona("noisy", lambda day: 0.70, median_seconds=3.0),
    Persona("drifter", lambda day: 0.95 if day <= 5 else 0.60, median_seconds=3.2),
    Persona("rusher", lambda day: 0.0, median_seconds=0.5, always_first_option=True),
]


def simulate(session: Session, reset: bool = False, seed: int = 7) -> Project:
    rng = random.Random(seed)
    existing = session.exec(select(Project).where(Project.name == PROJECT_NAME)).first()
    if existing is not None:
        if not reset:
            print(f"'{PROJECT_NAME}' already exists; pass --reset to simulate again")
            return existing
        session.delete(existing)
        session.commit()

    admin = session.exec(select(User).where(User.role == Role.admin)).first()
    if admin is None:
        raise SystemExit("Run `python -m app.seed` first to create the admin account")

    project = Project(
        name=PROJECT_NAME,
        task_type=TaskType.image_classification,
        label_options=CIFAR_CLASSES,
        gold_rate=0.2,
        overlap_rate=0.25,
        overlap_labelers=3,
        target_error_rate=0.1,
        created_by=admin.id,
    )
    session.add(project)
    session.flush()
    truth = _create_items(session, project, rng)
    labelers = _create_labelers(session, project)
    session.commit()

    start = datetime.combine(datetime.now(UTC).date() - timedelta(days=DAYS), time(9), UTC)
    for day in range(1, DAYS + 1):
        day_start = start + timedelta(days=day - 1)
        clocks = {p.name: day_start for p in PERSONAS}
        # Round-robin so overlap items fill up across labelers the way they would live.
        for _ in range(LABELS_PER_DAY):
            for persona in PERSONAS:
                user = labelers[persona.name]
                assignment = get_or_assign_next(session, project, user, rng)
                if assignment is None:
                    raise SystemExit("Ran out of items; raise COPIES_PER_IMAGE")
                ms = _time_spent_ms(persona, rng)
                clocks[persona.name] += timedelta(milliseconds=ms + rng.randint(500, 4000))
                value = _answer(persona, day, truth[assignment.item_id], rng)
                submit_label(session, assignment, user, value, ms, at=clocks[persona.name])
        print(f"Day {day}: {LABELS_PER_DAY} labels each from {len(PERSONAS)} labelers")
    return project


def _create_items(session: Session, project: Project, rng: random.Random) -> dict[int, str]:
    """Create items from the CIFAR sample and return each item's true class."""
    if not CIFAR_CSV.exists():
        raise SystemExit(f"{CIFAR_CSV} not found; run scripts/fetch_cifar_sample.py first")
    with CIFAR_CSV.open() as f:
        images = [(r["image_url"], r.get("true_label")) for r in csv.DictReader(f)]
    if any(not label for _, label in images):
        raise SystemExit(f"{CIFAR_CSV.name} has no true_label column; rerun the fetch script")

    items: list[tuple[Item, str]] = []
    for _ in range(COPIES_PER_IMAGE):
        for url, label in images:
            gold = label if rng.random() < GOLD_SHARE else None
            overlap = gold is None and rng.random() < project.overlap_rate
            item = Item(
                project_id=project.id,
                payload={"image_url": url},
                gold_answer=gold,
                required_labels=project.overlap_labelers if overlap else 1,
            )
            items.append((item, label))
    session.add_all(item for item, _ in items)
    session.flush()
    return {item.id: label for item, label in items}


def _create_labelers(session: Session, project: Project) -> dict[str, User]:
    labelers = {}
    password_hash = hash_password("gauge-demo")
    for persona in PERSONAS:
        user = session.exec(select(User).where(User.email == persona.email)).first()
        if user is None:
            user = User(email=persona.email, password_hash=password_hash, role=Role.labeler)
            session.add(user)
            session.flush()
        session.add(ProjectMember(project_id=project.id, user_id=user.id))
        labelers[persona.name] = user
    reviewer = session.exec(select(User).where(User.role == Role.reviewer)).first()
    if reviewer is not None:
        session.add(ProjectMember(project_id=project.id, user_id=reviewer.id))
    return labelers


def _answer(persona: Persona, day: int, truth: str, rng: random.Random) -> str:
    if persona.always_first_option:
        return CIFAR_CLASSES[0]
    if rng.random() < persona.accuracy(day):
        return truth
    return rng.choice([c for c in CIFAR_CLASSES if c != truth])


def _time_spent_ms(persona: Persona, rng: random.Random) -> int:
    # Log-normal: most labels near the median, with a long tail of slow ones.
    seconds = rng.lognormvariate(math.log(persona.median_seconds), 0.35)
    return int(seconds * 1000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="delete and re-simulate")
    args = parser.parse_args()
    with Session(get_engine()) as session:
        simulate(session, reset=args.reset)


if __name__ == "__main__":
    main()
