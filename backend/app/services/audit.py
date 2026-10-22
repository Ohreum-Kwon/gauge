from typing import Any

from sqlmodel import Session

from app.models import AuditLog, User


def record(
    session: Session,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: int | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the session. It commits with the change it describes."""
    session.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
        )
    )
