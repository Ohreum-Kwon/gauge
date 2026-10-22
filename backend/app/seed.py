"""Create demo accounts and a demo project. Safe to run more than once.

    uv run python -m app.seed

Every demo account uses the password in GAUGE_DEMO_PASSWORD (default "gauge-demo").
"""

import os
from pathlib import Path

from sqlmodel import Session, select

from app.db import get_engine
from app.models import Item, Project, ProjectMember, Role, TaskType, User
from app.security import hash_password
from app.services.ingest import parse_items

DEMO_USERS = [
    ("admin@gauge.dev", Role.admin),
    ("reviewer@gauge.dev", Role.reviewer),
    *((f"labeler{n}@gauge.dev", Role.labeler) for n in range(1, 5)),
]
CIFAR_CLASSES = [
    "airplane", "automobile", "bird", "cat", "deer",
    "dog", "frog", "horse", "ship", "truck",
]  # fmt: skip
CIFAR_CSV = Path(__file__).resolve().parent.parent / "sample_data" / "cifar10_sample.csv"


def seed(session: Session) -> None:
    password_hash = hash_password(os.environ.get("GAUGE_DEMO_PASSWORD", "gauge-demo"))
    users: dict[str, User] = {}
    for email, role in DEMO_USERS:
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, password_hash=password_hash, role=role)
            session.add(user)
        users[email] = user
    session.flush()

    name = "CIFAR-10 demo"
    if session.exec(select(Project).where(Project.name == name)).first() is None:
        project = Project(
            name=name,
            task_type=TaskType.image_classification,
            label_options=CIFAR_CLASSES,
            created_by=users["admin@gauge.dev"].id,
        )
        session.add(project)
        session.flush()
        session.add_all(
            ProjectMember(project_id=project.id, user_id=u.id)
            for u in users.values()
            if u.role != Role.admin
        )
        if CIFAR_CSV.exists():
            parsed = parse_items(
                CIFAR_CSV.name, CIFAR_CSV.read_bytes(), project.task_type, CIFAR_CLASSES
            )
            session.add_all(
                Item(project_id=project.id, payload=p.payload, gold_answer=p.gold_answer)
                for p in parsed
            )
            print(f"Loaded {len(parsed)} items from {CIFAR_CSV.name}")
        else:
            print(f"{CIFAR_CSV} not found; created the project with no items")
    session.commit()
    print("Demo accounts:", ", ".join(email for email, _ in DEMO_USERS))


if __name__ == "__main__":
    with Session(get_engine()) as session:
        seed(session)
