"""Backend de sistema para macOS (lo selecciona services/system.py).

La persistencia usa un LaunchAgent del usuario (sin admin):
  RunAtLoad  -> arranca al iniciar sesión
  KeepAlive  -> lo vuelve a abrir si lo cierran/matan
El "cierre autorizado" descarga el agente (launchctl unload) para que KeepAlive no lo reabra;
el .plist queda en disco, así en el próximo inicio de sesión vuelve a cargar.
"""
from __future__ import annotations

import ctypes
import logging
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from shared import config

__all__ = ["single_instance", "input_idle_seconds", "message_box", "enable_autostart",
           "disable_autostart", "write_heartbeat", "mark_stopped", "clear_stopped",
           "request_update", "take_killed_alert"]

log = logging.getLogger("ddt.system")

_LABEL = config.LAUNCH_AGENT_LABEL
_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_lock_fd = None


# ---------- instancia única ----------

def single_instance() -> bool:
    global _lock_fd
    import fcntl

    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _lock_fd = os.open(str(config.DATA_DIR / "instance.lock"), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False  # otra instancia ya tiene el lock


# ---------- inactividad ----------

_cg = None


def _coregraphics():
    global _cg
    if _cg is None:
        for path in ("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
                     "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
                     "/System/Library/Frameworks/Quartz.framework/Quartz"):
            try:
                _cg = ctypes.CDLL(path)
                _cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
                _cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
                break
            except (OSError, AttributeError):
                _cg = None
    return _cg


def input_idle_seconds() -> float | None:
    """Segundos desde el último teclado/mouse (kCGEventSourceStateHIDSystemState, cualquier evento)."""
    cg = _coregraphics()
    if cg is None:
        return None
    try:
        return float(cg.CGEventSourceSecondsSinceLastEventType(1, 0xFFFFFFFF))
    except Exception:  # noqa: BLE001
        return None


def message_box(text: str) -> None:
    try:
        subprocess.Popen(["osascript", "-e",
                          f'display dialog {_as(text)} with title {_as(config.APP_NAME)} '
                          'buttons {"OK"} default button "OK" with icon note'])
    except OSError:
        log.info("message_box: %s", text)


def _as(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------- LaunchAgent (autoarranque + reabrir si lo cierran) ----------

def _launch_args() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--autostart"]
    script = Path(sys.modules["__main__"].__file__).resolve()
    return [str(Path(sys.executable).resolve()), str(script), "--autostart"]


def _launchctl(*args: str) -> None:
    try:
        subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("launchctl %s: %s", args[0] if args else "", exc)


def enable_autostart() -> None:
    """Escribe el LaunchAgent (RunAtLoad + KeepAlive) y lo carga. Idempotente."""
    _PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": _LABEL,
        "ProgramArguments": _launch_args(),
        "RunAtLoad": True,
        "KeepAlive": True,  # lo reabre si lo cierran o lo matan
        "ProcessType": "Interactive",
        "WorkingDirectory": str(config.DATA_DIR),
    }
    try:
        _PLIST.write_bytes(plistlib.dumps(plist))
    except OSError as exc:
        log.warning("no se pudo escribir el LaunchAgent: %s", exc)
        return
    _launchctl("unload", str(_PLIST))  # recargar por si cambió
    _launchctl("load", "-w", str(_PLIST))


def disable_autostart() -> None:
    _launchctl("unload", str(_PLIST))
    _PLIST.unlink(missing_ok=True)


# ---------- marcadores (paridad con el backend Windows) ----------

def write_heartbeat() -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / config.ALIVE_NAME).write_text(str(int(time.time())), encoding="ascii")
    except OSError:
        pass


def mark_stopped() -> None:
    """Cierre autorizado: descarga el LaunchAgent para que KeepAlive no lo reabra esta sesión."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / config.STOPPED_NAME).write_text(str(int(time.time())), encoding="ascii")
    except OSError:
        pass
    _launchctl("unload", str(_PLIST))  # el .plist queda: vuelve en el próximo inicio de sesión


def clear_stopped() -> None:
    (config.DATA_DIR / config.STOPPED_NAME).unlink(missing_ok=True)


def request_update() -> None:
    # La versión Mac (interna, sin firmar) no tiene auto-actualización; se actualiza reinstalando el .app
    log.info("request_update: no disponible en macOS")


def take_killed_alert() -> dict | None:
    # Con KeepAlive el reinicio es automático; no se distingue cierre forzado de arranque normal
    return None
