from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, make_url
from sqlmodel import Session, create_engine

from app.config import get_settings


@lru_cache
def get_engine(direct: bool = False) -> Engine:
    """The app's engine. direct=True skips Neon's PgBouncer pooler, which migrations
    need: they rely on session state that transaction pooling doesn't keep."""
    url = get_settings().database_url
    # Render and Neon hand out postgres:// URLs; SQLAlchemy needs the driver named.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = make_url(url)
    # Neon's direct host is the pooled one without "-pooler".
    if direct and parsed.host and "-pooler." in parsed.host:
        parsed = parsed.set(host=parsed.host.replace("-pooler.", ".", 1))
    return create_engine(parsed, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
