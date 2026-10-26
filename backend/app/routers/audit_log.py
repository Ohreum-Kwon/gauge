from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, func, select

from app.db import get_session
from app.deps import require_role
from app.models import AuditLog, Role, User
from app.schemas import AuditEntryOut, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit_entries(
    _: User = Depends(require_role(Role.admin)),
    session: Session = Depends(get_session),
    action: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> AuditPage:
    """Every recorded change, newest first, optionally filtered to one action."""
    query = select(AuditLog, User.email).outerjoin(User, col(AuditLog.actor_id) == User.id)
    count = select(func.count()).select_from(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
        count = count.where(AuditLog.action == action)
    rows = session.exec(query.order_by(col(AuditLog.id).desc()).offset(offset).limit(limit)).all()
    return AuditPage(
        total=session.exec(count).one(),
        entries=[
            AuditEntryOut(
                id=entry.id,
                actor_email=email,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                before=entry.before,
                after=entry.after,
                created_at=entry.created_at,
            )
            for entry, email in rows
        ],
    )
