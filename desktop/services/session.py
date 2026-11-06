"""Sesión de tienda guardada. En Windows se cifra con DPAPI (solo la descifra el mismo usuario).
En macOS se guarda en un archivo con permisos 0600 dentro del perfil del usuario."""
from __future__ import annotations

import json
import sys

from shared import config

_FILE = config.DATA_DIR / "session.dat"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _call(fn, data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        if not fn(ctypes.byref(blob_in), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN,
                  ctypes.byref(blob_out)):
            raise OSError("DPAPI falló")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def save(token: str, user: dict) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        blob = _call(ctypes.windll.crypt32.CryptProtectData,
                     json.dumps({"token": token, "user": user}).encode())
        _FILE.write_bytes(blob)

    def load() -> dict | None:
        try:
            return json.loads(_call(ctypes.windll.crypt32.CryptUnprotectData, _FILE.read_bytes()))
        except (OSError, ValueError):
            return None

else:
    import os

    def save(token: str, user: dict) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps({"token": token, "user": user}), encoding="utf-8")
        try:
            os.chmod(_FILE, 0o600)  # solo el dueño puede leer la sesión
        except OSError:
            pass

    def load() -> dict | None:
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def clear() -> None:
    _FILE.unlink(missing_ok=True)
