from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.helpers import repo
from src.helpers.security import decode_token

bearer = HTTPBearer(auto_error=False)


def user_from_token(token: str) -> dict | None:
    claims = decode_token(token)
    if not claims:
        return None
    user = repo.get_user(int(claims["sub"]))
    if not user or not user["active"] or user["token_version"] != claims.get("ver"):
        return None
    return user


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    user = user_from_token(creds.credentials) if creds else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo administradores")
    return user
