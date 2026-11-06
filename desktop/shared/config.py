from __future__ import annotations

import os
import socket
import ssl
import sys
from pathlib import Path

APP_NAME = "DDT Error Monitor"
APP_ID = "DDTMonitor"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
LAUNCH_AGENT_LABEL = "com.distefano.ddtmonitor"  # macOS LaunchAgent

# En la app empaquetada (PyInstaller) los recursos viven en sys._MEIPASS
if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).resolve().parent)))
else:
    ROOT = Path(__file__).resolve().parent.parent

# DDT_SERVER permite apuntar a un backend local en desarrollo (http://127.0.0.1:8765)
SERVER = os.getenv("DDT_SERVER", "https://45.79.170.84:9443").rstrip("/")
WS_SERVER = "ws" + SERVER[4:]  # http -> ws, https -> wss

CA_FILE = ROOT / "shared" / "ddt_ca.crt"
# Llave pública Ed25519 de las actualizaciones (la privada está solo en la PC del desarrollador)
UPDATE_PUBKEY = "d734f3a46777c5fd50c0d63a8ede1e2101128e38e54184e8a033c279ed742ce4"
ICON_FILE = ROOT / "assets" / "ddt.ico"
if IS_MAC:
    DATA_DIR = Path.home() / "Library" / "Application Support" / APP_ID
else:
    DATA_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / APP_ID
HOSTNAME = socket.gethostname()

# Modo portable: sin instalador ni tarea SYSTEM. La persistencia (autoarranque + reabrir si lo cierran)
# es a nivel de usuario (no necesita admin), por eso es más débil: ver updater.user_watchdog().
PORTABLE = (ROOT / "portable.flag").exists()

# Marcadores que coordinan la app (usuario) con el watchdog (SYSTEM), en DATA_DIR de cada usuario
ALIVE_NAME = "agent.alive"      # señal de vida del agente; su antigüedad distingue "lo mataron" de "arranque"
STOPPED_NAME = "stopped.flag"   # cierre autorizado con clave de admin: el watchdog NO debe reabrir
KILLED_NAME = "killed.flag"     # el watchdog lo escribe al reabrir tras un cierre forzado; la app lo reporta
UPDATE_NAME = "update.flag"     # el admin pidió "Actualizar ahora": el watchdog corre el actualizador (solo firmado)
HEARTBEAT_SECONDS = 30
KILL_WINDOW_SECONDS = 120       # señal de vida más nueva que esto = el proceso murió hace poco (no fue arranque)


def _ssl_context() -> ssl.SSLContext | None:
    if not SERVER.startswith("https"):
        return None
    # Solo se confía en la CA propia del servidor (Caddy, sin dominio público)
    return ssl.create_default_context(cafile=str(CA_FILE))


SSL_CTX = _ssl_context()
