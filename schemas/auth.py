from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models import Role, UserStatus


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    # Admins can't self-register; they're created with scripts/create_admin.py
    role: Role = Role.CUSTOMER

    @field_validator("role")
    @classmethod
    def no_self_service_admin(cls, value: Role) -> Role:
        if value == Role.ADMIN:
            raise ValueError("Choose 'customer' or 'organizer'")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: Role
    status: UserStatus
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
