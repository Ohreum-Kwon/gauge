"""Tests run against a real Postgres database (gauge_test by default), because the queue
relies on Postgres row locking. Each test runs inside a transaction that is rolled back
afterwards, so tests don't see each other's data."""

import os
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.db import get_session
from app.main import create_app
from app.models import Role, User
from app.security import create_access_token, hash_password

TEST_DATABASE_URL = os.environ.get(
    "GAUGE_TEST_DATABASE_URL", "postgresql+psycopg://gauge:gauge@localhost:5432/gauge_test"
)

Headers = dict[str, str]


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        # Commits inside the app release a savepoint instead of the outer transaction.
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client


@pytest.fixture
def make_user(session: Session) -> Callable[..., tuple[User, Headers]]:
    count = 0

    def make(role: Role, password: str = "password123") -> tuple[User, Headers]:
        nonlocal count
        count += 1
        user = User(
            email=f"{role}{count}@example.com", password_hash=hash_password(password), role=role
        )
        session.add(user)
        session.commit()
        return user, {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return make


@pytest.fixture
def admin(make_user) -> Headers:
    return make_user(Role.admin)[1]


@pytest.fixture
def make_project(client: TestClient, admin: Headers) -> Callable[..., dict]:
    def make(**overrides) -> dict:
        body = {
            "name": "Animals",
            "task_type": "image_classification",
            "label_options": ["cat", "dog", "bird"],
        } | overrides
        response = client.post("/api/projects", json=body, headers=admin)
        assert response.status_code == 201, response.text
        return response.json()

    return make


def upload_csv(client: TestClient, project_id: int, headers: Headers, csv_text: str):
    return client.post(
        f"/api/projects/{project_id}/items",
        files={"file": ("items.csv", csv_text.encode(), "text/csv")},
        headers=headers,
    )
