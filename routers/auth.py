from typing import Annotated

from config import settings
from exceptions import ConflictError, ForbiddenError
from rate_limit import limiter
from security import create_access_token, hash_password, verify_password
from dependencies import CurrentUser, DbSession
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from models import User, UserStatus
from schemas.auth import Token, UserCreate, UserOut
from sqlalchemy import select

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
def register(request: Request, data: UserCreate, db: DbSession):
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("Email already registered")
    user = User(
        email=email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
@limiter.limit(settings.rate_limit_auth)
def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Use your email as `username`. Works with the Swagger 'Authorize' button."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            401, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
        )
    if user.status != UserStatus.ACTIVE:
        raise ForbiddenError(f"Your account is {user.status}")
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
