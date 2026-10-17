from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    accept_terms: bool = False  # ticked on the sign-in screen; the time is stored on the user


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)


class RegisterIn(UserCreate):
    workspace_name: str = Field(default="My Workspace", max_length=120)
    accept_terms: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    workspace_name: str
    role: str
    created_at: datetime
    terms_accepted_at: datetime | None = None
    language: str = "en"


class RoleIn(BaseModel):
    role: Literal["owner", "member"]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
