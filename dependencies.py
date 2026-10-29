from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from core.database import get_db
from core.exceptions import ForbiddenError
from core.security import decode_access_token
from models import Role, User, UserStatus

DbSession = Annotated[Session, Depends(get_db)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _load_user(db: Session, token: str) -> User:
    user_id = decode_access_token(token)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status != UserStatus.ACTIVE:
        raise ForbiddenError(f"Your account is {user.status.value}")
    return user


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    return _load_user(db, token)


def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_optional)], db: DbSession
) -> User | None:
    return _load_user(db, token) if token else None


def require_roles(*roles: Role):
    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to do this")
        return user

    return checker


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
CurrentOrganizer = Annotated[User, Depends(require_roles(Role.ORGANIZER))]
CurrentAdmin = Annotated[User, Depends(require_roles(Role.ADMIN))]
