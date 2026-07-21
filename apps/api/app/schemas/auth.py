from pydantic import BaseModel, Field

from app.schemas.users import UserRead


class LoginRequest(BaseModel):
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AuthUserResponse(BaseModel):
    user: UserRead
