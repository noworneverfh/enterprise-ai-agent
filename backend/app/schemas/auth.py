from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)
    role: str = "viewer"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str) -> str:
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("username must not be empty.")
        return normalized

    @field_validator("role")
    @classmethod
    def normalize_role(cls, role: str) -> str:
        normalized = role.strip().lower()
        if normalized not in {"admin", "engineer", "viewer"}:
            raise ValueError("role must be admin, engineer, or viewer.")
        return normalized


class UserLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, username: str) -> str:
        return username.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    roles: list[str]
    permissions: list[str]
    created_at: datetime
