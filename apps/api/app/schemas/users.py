from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Role, UserStatus


class UserRead(BaseModel):
    id: UUID
    login: str
    display_name: str
    role: Role
    status: UserStatus

    model_config = ConfigDict(from_attributes=True)


class UsersListResponse(BaseModel):
    users: list[UserRead]


class UserCreate(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.USER
    status: UserStatus = UserStatus.ACTIVE


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    role: Role | None = None
    status: UserStatus | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=256)
