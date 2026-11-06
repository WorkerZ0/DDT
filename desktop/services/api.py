from __future__ import annotations

import json
import urllib.error
import urllib.request

from shared import config


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


_FIELD_HINTS = {
    "username": "Usuario: 3 a 32 caracteres (letras, números, . _ -)",
    "password": "Contraseña: mínimo 6 caracteres",
    "display_name": "Nombre: máximo 80 caracteres",
}


def _error_message(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        field = (detail[0].get("loc") or [""])[-1]
        return _FIELD_HINTS.get(field, "Datos inválidos")
    return f"Error del servidor ({status})"


class Api:
    def __init__(self, token: str | None = None):
        self.token = token

    def _request(self, method: str, path: str, body: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(config.SERVER + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=config.SSL_CTX, timeout=15) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code, _error_message(exc.code, exc.read())) from None
        except (urllib.error.URLError, OSError):
            raise ApiError(0, "Sin conexión con el servidor") from None
        return json.loads(raw) if raw else None

    def login(self, username: str, password: str) -> dict:
        return self._request("POST", "/api/auth/login", {"username": username, "password": password})

    def me(self) -> dict:
        return self._request("GET", "/api/auth/me")

    def users(self) -> list[dict]:
        return self._request("GET", "/api/users")

    def create_user(self, **fields) -> dict:
        return self._request("POST", "/api/users", fields)

    def update_user(self, user_id: int, **fields) -> dict:
        return self._request("PATCH", f"/api/users/{user_id}", fields)

    def delete_user(self, user_id: int) -> None:
        self._request("DELETE", f"/api/users/{user_id}")

    def delete_device(self, device_id: int) -> None:
        self._request("DELETE", f"/api/devices/{device_id}")
