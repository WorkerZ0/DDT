import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.helpers import repo
from src.helpers.hub import hub
from src.middlewares.auth import require_admin

router = APIRouter(prefix="/api/users", tags=["users"])

Role = Literal["admin", "tienda"]


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,32}$")
    password: str = Field(min_length=6, max_length=128)
    role: Role = "tienda"
    display_name: str = Field("", max_length=80)


class UserPatch(BaseModel):
    password: str | None = Field(None, min_length=6, max_length=128)
    role: Role | None = None
    display_name: str | None = Field(None, max_length=80)
    active: bool | None = None


def _get_or_404(user_id: int) -> dict:
    user = repo.get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return user


def _guard_last_admin(user: dict, losing_admin: bool) -> None:
    if losing_admin and user["role"] == "admin" and user["active"] and repo.count_active_admins() <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes quitar el último administrador")


@router.get("")
def list_users(_: dict = Depends(require_admin)):
    return repo.list_users()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserIn, _: dict = Depends(require_admin)):
    try:
        user = await run_in_threadpool(
            repo.create_user, body.username, body.password, body.role, body.display_name
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese usuario ya existe")
    return repo.public_user(user)


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UserPatch, _: dict = Depends(require_admin)):
    user = _get_or_404(user_id)
    _guard_last_admin(user, body.role == "tienda" or body.active is False)
    updated, revoked = await run_in_threadpool(
        lambda: repo.update_user(
            user_id,
            password=body.password,
            role=body.role,
            display_name=body.display_name,
            active=body.active,
        )
    )
    if revoked:
        hub.disconnect_user(user_id)
    hub.broadcast_devices()
    return repo.public_user(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes eliminar tu propio usuario")
    user = _get_or_404(user_id)
    _guard_last_admin(user, True)
    repo.delete_user(user_id)
    hub.disconnect_user(user_id)
    hub.broadcast_devices()
