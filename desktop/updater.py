"""Actualizador automático de DDT Monitor. Lo corre una tarea programada como SYSTEM (al encender y cada 30 min).

  updater.py                 busca versión nueva; si hay: la baja, verifica firma + SHA-256 e instala en silencio
  updater.py --install-task  crea la tarea programada (lo llama el instalador)
  updater.py --remove-task   la borra (lo llama el desinstalador)
  updater.py --relaunch      reabre la app en las sesiones donde estaba abierta (al final de una actualización)

El instalador cierra la app para reemplazar archivos; como corre como SYSTEM no puede abrirla de nuevo
en la sesión del cajero, por eso --relaunch la abre con el token de cada sesión (WTSQueryUserToken).
"""
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from ctypes import wintypes
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from xml.sax.saxutils import escape

from shared import config, ed25519
from shared.version import VERSION

APP_DIR = Path(__file__).resolve().parent
INSTALL_DIR = APP_DIR.parent
RUNTIME = INSTALL_DIR / "runtime"
# Dentro de Program Files: solo admins/SYSTEM escriben, un cajero no puede cambiar el .exe ya verificado
WORK_DIR = INSTALL_DIR / "updates"
RELAUNCH_FILE = WORK_DIR / "relaunch.json"
# Mientras se instala una actualización el agente desaparece: el watchdog no debe tomarlo como cierre forzado
UPDATING_FILE = WORK_DIR / "updating.flag"
UPDATING_GRACE_SECONDS = 15 * 60
TASK_NAME = "DDTMonitorUpdate"
WATCHDOG_TASK = "DDTMonitorWatchdog"
USER_WATCH_TASK = "DDTMonitorUserWatch"  # versión portable: tarea del usuario, sin admin
APP_EXE = "DDTMonitor.exe"
INSTALLER_NAME = re.compile(r"DDTMonitor-Setup-\d+(\.\d+)*\.exe")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_UNICODE_ENVIRONMENT = 0x00000400

log = logging.getLogger("ddt.updater")


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _open(name: str, timeout: int):
    return urllib.request.urlopen(f"{config.SERVER}/updates/{name}", context=config.SSL_CTX, timeout=timeout)


def _get(name: str) -> bytes:
    with _open(name, 30) as resp:
        return resp.read(1_000_000)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_manifest() -> dict:
    """latest.json firmado con la llave del desarrollador; sin firma válida no se instala nada."""
    manifest = _get("latest.json")
    signature = bytes.fromhex(_get("latest.json.sig").decode("ascii").strip())
    if not ed25519.verify(bytes.fromhex(config.UPDATE_PUBKEY), manifest, signature):
        raise ValueError("firma de latest.json inválida")
    info = json.loads(manifest)
    if not INSTALLER_NAME.fullmatch(info["file"]):
        raise ValueError(f"nombre de instalador inesperado: {info['file']}")
    return info


def download(info: dict) -> Path:
    target = WORK_DIR / info["file"]
    if target.exists() and _sha256(target) == info["sha256"]:
        return target
    part = target.with_name(target.name + ".part")
    h, total, size = hashlib.sha256(), 0, int(info["size"])
    with _open(info["file"], 60) as resp, open(part, "wb") as f:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            total += len(chunk)
            if total > size:
                raise ValueError("el instalador pesa más de lo anunciado")
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != info["sha256"]:
        part.unlink()
        raise ValueError("SHA-256 del instalador no coincide")
    os.replace(part, target)
    return target


def app_sessions() -> list[int]:
    """Sesiones de Windows (no la 0 de servicios) donde la app está abierta."""
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {APP_EXE}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, creationflags=CREATE_NO_WINDOW).stdout
    sessions = set()
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 4 and row[0].lower() == APP_EXE.lower() and row[3].strip().isdigit():
            sessions.add(int(row[3]))
    sessions.discard(0)
    return sorted(sessions)


# Archivos que deben existir; si falta alguno (p. ej. un borrado accidental) se reinstala la versión actual
CRITICAL_FILES = [
    "app/main.py", "app/updater.py", "app/shared/config.py", "app/shared/version.py",
    "app/services/agent.py", "app/services/viewer.py", "app/services/connection.py",
    "app/pages/admin.py", "app/pages/login.py", "app/pages/store.py", "app/assets/ddt.ico",
    "runtime/DDTMonitor.exe", "runtime/python.exe", "runtime/pythonw.exe",
]


def integrity_broken() -> bool:
    missing = [f for f in CRITICAL_FILES if not (INSTALL_DIR / f).exists()]
    if missing:
        log.warning("integridad: faltan archivos %s", missing)
    return bool(missing)


def _apply(info: dict, reason: str) -> None:
    log.info("%s: descargando %s", reason, info["file"])
    installer = download(info)
    for old in WORK_DIR.glob("DDTMonitor-Setup-*"):
        if old != installer:
            old.unlink()
    RELAUNCH_FILE.write_text(json.dumps(app_sessions()), encoding="utf-8")
    UPDATING_FILE.write_text(str(int(time.time())), encoding="ascii")
    log.info("instalando %s", installer.name)
    launch_installer(installer)


def check() -> None:
    info = fetch_manifest()
    if parse_version(info["version"]) > parse_version(VERSION):
        _apply(info, f"versión nueva {info['version']} (instalada {VERSION})")
    elif integrity_broken():
        # Mismo nº de versión: reinstalar la actual repara los archivos faltantes (el instalador rehace todo)
        _apply(info, "reparando instalación (archivos faltantes)")
    else:
        log.info("al día (%s) e íntegro", VERSION)


def launch_installer(installer: Path) -> None:
    # Separado de este proceso: el instalador reemplaza el runtime con el que corre este script
    subprocess.Popen([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                      f"/LOG={WORK_DIR / 'install.log'}"],
                     cwd=str(WORK_DIR), close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)


# ---------- reabrir la app en la sesión del usuario ----------

class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def start_in_session(session_id: int) -> bool:
    wtsapi = ctypes.WinDLL("wtsapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi.WTSQueryUserToken.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.HANDLE)]
    userenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL]
    userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    advapi.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_StartupInfo), ctypes.POINTER(_ProcessInfo)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    token = wintypes.HANDLE()
    if not wtsapi.WTSQueryUserToken(session_id, ctypes.byref(token)):
        log.warning("sesión %s sin usuario (error %s)", session_id, ctypes.get_last_error())
        return False
    env = ctypes.c_void_p()
    try:
        # Entorno del usuario: la app guarda su sesión en %APPDATA% de ese usuario
        if not userenv.CreateEnvironmentBlock(ctypes.byref(env), token, False):
            env = ctypes.c_void_p()
        exe = str(RUNTIME / APP_EXE)
        cmd = ctypes.create_unicode_buffer(f'"{exe}" "{APP_DIR / "main.py"}" --autostart')
        si = _StartupInfo(cb=ctypes.sizeof(_StartupInfo), lpDesktop="winsta0\\default")
        pi = _ProcessInfo()
        if not advapi.CreateProcessAsUserW(token, exe, cmd, None, None, False, CREATE_UNICODE_ENVIRONMENT,
                                           env, str(APP_DIR), ctypes.byref(si), ctypes.byref(pi)):
            log.warning("no se pudo abrir la app en la sesión %s (error %s)", session_id, ctypes.get_last_error())
            return False
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        log.info("app reabierta en la sesión %s", session_id)
        return True
    finally:
        if env:
            userenv.DestroyEnvironmentBlock(env)
        kernel32.CloseHandle(token)


def relaunch() -> None:
    UPDATING_FILE.unlink(missing_ok=True)  # la instalación terminó: el watchdog vuelve a vigilar
    try:
        sessions = json.loads(RELAUNCH_FILE.read_text(encoding="utf-8"))
        RELAUNCH_FILE.unlink()
    except (OSError, ValueError):
        return
    for session_id in sessions:
        start_in_session(int(session_id))


# ---------- watchdog: reabre el agente de tienda si lo cierran ----------

class _WtsSessionInfo(ctypes.Structure):
    _fields_ = [("SessionId", wintypes.DWORD), ("pWinStationName", wintypes.LPWSTR), ("State", ctypes.c_int)]


def user_sessions() -> list[tuple[int, wintypes.HANDLE]]:
    """(session_id, token) de cada sesión con un usuario conectado. El llamador cierra cada token."""
    wtsapi = ctypes.WinDLL("wtsapi32", use_last_error=True)
    wtsapi.WTSEnumerateSessionsW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                             ctypes.POINTER(ctypes.POINTER(_WtsSessionInfo)),
                                             ctypes.POINTER(wintypes.DWORD)]
    wtsapi.WTSQueryUserToken.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.HANDLE)]
    wtsapi.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    info = ctypes.POINTER(_WtsSessionInfo)()
    count = wintypes.DWORD()
    if not wtsapi.WTSEnumerateSessionsW(0, 0, 1, ctypes.byref(info), ctypes.byref(count)):
        log.warning("WTSEnumerateSessions falló (%s)", ctypes.get_last_error())
        return []
    out = []
    try:
        for i in range(count.value):
            sid = info[i].SessionId
            token = wintypes.HANDLE()
            if sid != 0 and wtsapi.WTSQueryUserToken(sid, ctypes.byref(token)):
                out.append((sid, token))
    finally:
        wtsapi.WTSFreeMemory(info)
    return out


def _data_dir(token: wintypes.HANDLE) -> Path | None:
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    userenv.GetUserProfileDirectoryW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    size = wintypes.DWORD(0)
    userenv.GetUserProfileDirectoryW(token, None, ctypes.byref(size))
    if not size.value:
        return None
    buf = ctypes.create_unicode_buffer(size.value)
    if not userenv.GetUserProfileDirectoryW(token, buf, ctypes.byref(size)):
        return None
    return Path(buf.value) / "AppData" / "Roaming" / config.APP_ID


def watchdog() -> None:
    """Si una PC de tienda (tiene sesión guardada) dejó de ejecutar el agente, lo reabre.

    Señal de vida reciente + proceso ausente = lo cerraron a la fuerza: se reabre y se avisa al admin.
    Señal vieja/ausente = arranque o login: se reabre callado. Cierre autorizado = no se toca.
    """
    try:
        if time.time() - UPDATING_FILE.stat().st_mtime < UPDATING_GRACE_SECONDS:
            return  # se está instalando una actualización/reparación: el agente falta a propósito
    except OSError:
        pass
    # Chequeo de integridad cada minuto (local, barato): si falta un archivo, repara ya sin esperar los 30 min
    if integrity_broken():
        log.warning("watchdog: instalación incompleta, reparando")
        try:
            check()  # re-baja el instalador firmado y reinstala; deja la reparación en curso
        except Exception:
            log.exception("reparación desde el watchdog falló")
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    running = set(app_sessions())
    update_requested = False
    for sid, token in user_sessions():
        try:
            data = _data_dir(token)
            if data is None or not (data / "session.dat").exists():
                continue  # no es PC de tienda
            flag = data / config.UPDATE_NAME
            if flag.exists():
                update_requested = True
                flag.unlink(missing_ok=True)
            if sid in running:
                continue  # el agente ya corre
            if (data / config.STOPPED_NAME).exists():
                continue  # cierre autorizado con clave de admin
            alive = data / config.ALIVE_NAME
            try:
                forced = time.time() - alive.stat().st_mtime <= config.KILL_WINDOW_SECONDS
            except OSError:
                forced = False
            if forced:
                log.warning("watchdog: agente ausente en sesión %s con señal reciente (cierre forzado)", sid)
                try:
                    (data / config.KILLED_NAME).write_text(str(int(time.time())), encoding="ascii")
                except OSError:
                    pass
            else:
                log.info("watchdog: reabriendo agente en sesión %s (arranque/login)", sid)
            start_in_session(sid)
        finally:
            kernel32.CloseHandle(token)
    if update_requested:
        # Pedido desde el admin: misma revisión que la tarea de actualización (solo instala lo firmado)
        log.info("watchdog: el admin pidió actualizar ahora")
        try:
            check()
        except Exception:
            log.exception("actualización pedida por el admin falló")


# ---------- modo portable: persistencia a nivel de usuario (sin admin) ----------
#
# El modo instalado usa dos tareas SYSTEM (actualizar + watchdog) que exigen admin.
# El modo portable no puede crearlas, así que corre un watchdog como el PROPIO usuario:
# una tarea programada del usuario (cualquiera puede crear tareas para sí mismo) que cada
# minuto revisa SOLO su sesión y reabre la app si la cerraron. Es honesto y más débil que el
# SYSTEM: si matan la app Y borran la tarea no vuelve hasta el próximo inicio de sesión, y no
# ve otras sesiones. Tampoco auto-actualiza (el instalador firmado necesita admin).

def _runtime_pythonw() -> Path:
    """pythonw.exe del runtime que realmente está en uso (portable trae modern y legacy)."""
    exe = Path(sys.executable)
    return exe.with_name("pythonw.exe") if exe.name.lower() != "pythonw.exe" else exe


def _portable_app_exe() -> str:
    """DDTMonitor.exe (pythonw renombrado, sin consola) del runtime en uso."""
    return str(_runtime_pythonw().with_name(APP_EXE))


def _current_session() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sid = wintypes.DWORD()
    kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    return sid.value


def user_watchdog() -> None:
    """Portable: reabre el agente SOLO en la sesión actual del usuario, sin privilegios de admin.

    Misma lógica de marcadores que el watchdog SYSTEM, pero sin WTS: lee el %APPDATA% propio y
    relanza con subprocess (misma sesión). No repara ni actualiza (eso exige admin)."""
    try:
        if time.time() - UPDATING_FILE.stat().st_mtime < UPDATING_GRACE_SECONDS:
            return
    except OSError:
        pass
    data = config.DATA_DIR
    if not (data / "session.dat").exists():
        return  # esta PC no está configurada como tienda
    if _current_session() in set(app_sessions()):
        return  # el agente ya corre en esta sesión
    if (data / config.STOPPED_NAME).exists():
        return  # cierre autorizado con clave de admin: no reabrir
    alive = data / config.ALIVE_NAME
    try:
        forced = time.time() - alive.stat().st_mtime <= config.KILL_WINDOW_SECONDS
    except OSError:
        forced = False
    if forced:
        log.warning("user-watchdog: agente ausente con señal reciente (cierre forzado)")
        try:
            (data / config.KILLED_NAME).write_text(str(int(time.time())), encoding="ascii")
        except OSError:
            pass
    else:
        log.info("user-watchdog: reabriendo agente (arranque/login)")
    subprocess.Popen([_portable_app_exe(), str(APP_DIR / "main.py"), "--autostart"],
                     cwd=str(APP_DIR), close_fds=True,
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)


def user_task_xml() -> str:
    """Tarea del usuario actual (LeastPrivilege): al iniciar sesión y cada minuto."""
    start = datetime.now().replace(microsecond=0).isoformat()
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    principal = escape(f"{domain}\\{user}" if domain and user else user)
    logon_user = f"<UserId>{principal}</UserId>" if principal else ""
    exe = escape(str(_runtime_pythonw()))
    script = escape(f'"{APP_DIR / "updater.py"}" --user-watchdog')
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Reabre DDT Monitor si se cierra (version portable, sin admin)</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Delay>PT20S</Delay>{logon_user}</LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>{principal}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{exe}</Command><Arguments>{script}</Arguments><WorkingDirectory>{escape(str(APP_DIR))}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def ensure_user_watchdog() -> None:
    """Portable: crea/actualiza la tarea del usuario (idempotente). No necesita admin."""
    try:
        _create_task(USER_WATCH_TASK, user_task_xml())
    except Exception:
        log.exception("no se pudo crear la tarea de usuario (portable)")


def remove_user_watchdog() -> None:
    try:
        _schtasks("/Delete", "/F", "/TN", USER_WATCH_TASK)
    except RuntimeError as exc:
        log.info("%s", exc)


# ---------- tarea programada ----------

def task_xml() -> str:
    start = datetime.now().replace(microsecond=0).isoformat()
    exe = escape(str(RUNTIME / "pythonw.exe"))
    script = escape(f'"{APP_DIR / "updater.py"}"')
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Busca e instala actualizaciones de DDT Monitor</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Delay>PT3M</Delay></BootTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition><Interval>PT30M</Interval></Repetition>
      <RandomDelay>PT5M</RandomDelay>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="System">
    <Exec><Command>{exe}</Command><Arguments>{script}</Arguments><WorkingDirectory>{escape(str(APP_DIR))}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def watchdog_task_xml() -> str:
    """Cada minuto (y al arrancar/iniciar sesión) revisa que el agente de tienda siga corriendo."""
    start = datetime.now().replace(microsecond=0).isoformat()
    exe = escape(str(RUNTIME / "pythonw.exe"))
    script = escape(f'"{APP_DIR / "updater.py"}" --watchdog')
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Reabre DDT Monitor si se cierra en una PC de tienda</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Delay>PT1M</Delay></BootTrigger>
    <LogonTrigger><Delay>PT1M</Delay></LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions Context="System">
    <Exec><Command>{exe}</Command><Arguments>{script}</Arguments><WorkingDirectory>{escape(str(APP_DIR))}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def _schtasks(*args: str) -> None:
    result = subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"schtasks {args[0]}: {result.stdout.strip()} {result.stderr.strip()}")


def _create_task(name: str, xml: str) -> None:
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        _schtasks("/Create", "/F", "/TN", name, "/XML", path)
        log.info("tarea %s creada", name)
    finally:
        os.unlink(path)


def install_task() -> None:
    _create_task(TASK_NAME, task_xml())
    _create_task(WATCHDOG_TASK, watchdog_task_xml())


def remove_task() -> None:
    for name in (TASK_NAME, WATCHDOG_TASK):
        try:
            _schtasks("/Delete", "/F", "/TN", name)
        except RuntimeError as exc:
            log.info("%s", exc)


def main() -> None:
    WORK_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(WORK_DIR / "updater.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    actions = {"--install-task": install_task, "--remove-task": remove_task, "--relaunch": relaunch,
               "--watchdog": watchdog, "--user-watchdog": user_watchdog,
               "--user-install": ensure_user_watchdog, "--user-remove": remove_user_watchdog}
    try:
        actions.get(sys.argv[1] if len(sys.argv) > 1 else "", check)()
    except Exception:
        log.exception("falló %s", " ".join(sys.argv[1:]) or "chequeo")
        sys.exit(1)


if __name__ == "__main__":
    main()
