from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import require_role
from app.models import Role, User
from app.schemas import UserCreate, UserOut
from app.security import hash_password
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])

admin_only = require_role(Role.admin)


@router.get("")
def list_users(
    role: Role | None = None,
    _: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> list[UserOut]:
    query = select(User).order_by(col(User.id))
    if role is not None:
        query = query.where(User.role == role)
    return [UserOut.model_validate(u, from_attributes=True) for u in session.exec(query)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    admin: User = Depends(admin_only),
    session: Session = Depends(get_session),
) -> UserOut:
    email = body.email.lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists")
    user = User(email=email, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    session.flush()
    audit.record(
        session, admin, "user.create", "user", user.id, after={"email": email, "role": body.role}
    )
    session.commit()
    return UserOut.model_validate(user, from_attributes=True)
