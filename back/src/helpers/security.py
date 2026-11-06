import base64
import hashlib
import hmac
import os
import time

import jwt

from src.config import settings

_N, _R, _P = 2**14, 8, 1


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, dk = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=_N, r=_R, p=_P)
    return hmac.compare_digest(calc, base64.b64decode(dk))


# Para que un usuario inexistente tarde lo mismo que uno con clave errónea
DUMMY_HASH = hash_password(os.urandom(8).hex())


def create_token(user: dict) -> str:
    if user["role"] == "admin":
        ttl = settings.ADMIN_TOKEN_HOURS * 3600
    else:
        ttl = settings.AGENT_TOKEN_DAYS * 86400
    now = int(time.time())
    claims = {
        "sub": str(user["id"]),
        "role": user["role"],
        "ver": user["token_version"],
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except jwt.PyJWTError:
        return None
