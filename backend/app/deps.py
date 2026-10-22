from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.db import get_session
from app.models import Project, ProjectMember, Role, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    user_id = decode_access_token(token)
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: Role) -> Callable[[User], User]:
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return check


def get_visible_project(
    project_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Project:
    """Load a project the current user may see: admins see all, others only their own.

    Returns 404 rather than 403 for other people's projects so ids don't leak.
    """
    project = session.get(Project, project_id)
    is_member = user.role == Role.admin or (
        project is not None and session.get(ProjectMember, (project_id, user.id)) is not None
    )
    if project is None or not is_member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project
