from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.helpers import repo
from src.helpers.ratelimit import login_limiter
from src.helpers.security import DUMMY_HASH, create_token, verify_password
from src.middlewares.auth import current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    key = f"{ip}|{body.username.lower()}"
    if login_limiter.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Demasiados intentos, espera unos minutos")

    user = repo.get_user_by_username(body.username)
    ok = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    if not (user and ok and user["active"]):
        login_limiter.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")

    login_limiter.reset(key)
    return {"token": create_token(user), "user": repo.public_user(user)}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return repo.public_user(user)
