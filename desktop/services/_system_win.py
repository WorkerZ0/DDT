"""Backend de sistema para Windows (lo selecciona services/system.py)."""
from __future__ import annotations

import ctypes
import sys
import time
import winreg
from pathlib import Path

from shared import config

__all__ = ["single_instance", "input_idle_seconds", "message_box", "enable_autostart",
           "disable_autostart", "write_heartbeat", "mark_stopped", "clear_stopped",
           "request_update", "take_killed_alert"]

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_mutex = None


def single_instance() -> bool:
    global _mutex
    _mutex = _kernel32.CreateMutexW(None, False, f"Local\\{config.APP_ID}")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]


def input_idle_seconds() -> float | None:
    """Segundos desde el último uso de teclado o mouse en esta sesión de Windows."""
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000


def message_box(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, config.APP_NAME, 0x40)


def _launch_command() -> str:
    # Instalado: runtime\DDTMonitor.exe (pythonw renombrado). En desarrollo: python.exe -> pythonw.exe
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        exe = exe.with_name("pythonw.exe")
    script = Path(sys.modules["__main__"].__file__).resolve()
    return f'"{exe}" "{script}" --autostart'


def enable_autostart() -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, config.APP_ID, 0, winreg.REG_SZ, _launch_command())


def disable_autostart() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, config.APP_ID)
    except FileNotFoundError:
        pass


# ---------- marcadores para el watchdog (SYSTEM) ----------

def write_heartbeat() -> None:
    """Señal de vida del agente de tienda. El watchdog mira su antigüedad."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / config.ALIVE_NAME).write_text(str(int(time.time())), encoding="ascii")
    except OSError:
        pass


def mark_stopped() -> None:
    """Cierre autorizado (clave de admin): el watchdog no debe reabrir la app."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / config.STOPPED_NAME).write_text(str(int(time.time())), encoding="ascii")
    except OSError:
        pass


def clear_stopped() -> None:
    (config.DATA_DIR / config.STOPPED_NAME).unlink(missing_ok=True)


def request_update() -> None:
    """El admin pidió "Actualizar ahora": el watchdog (SYSTEM) lo ve en su próxima vuelta y corre el actualizador."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / config.UPDATE_NAME).write_text(str(int(time.time())), encoding="ascii")
    except OSError:
        pass


def take_killed_alert() -> dict | None:
    """Si el watchdog reabrió la app tras un cierre forzado, devuelve el aviso (una sola vez)."""
    path = config.DATA_DIR / config.KILLED_NAME
    try:
        data = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    path.unlink(missing_ok=True)
    try:
        at = int(data)
    except ValueError:
        at = int(time.time())
    # Ignora marcas viejas: solo reporta cierres recientes
    if time.time() - at > 3600:
        return None
    return {"event": "terminated", "at": at}
