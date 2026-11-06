# PyInstaller spec de DDT Monitor para macOS (interno, sin firmar, solo JPEG).
# Construir en un Mac:  pyinstaller --noconfirm --clean mac/ddt_mac.spec   (desde desktop/)
import os
import sys

from PyInstaller.utils.hooks import collect_all

APPDIR = os.path.abspath(os.path.join(SPECPATH, ".."))  # carpeta desktop/
sys.path.insert(0, APPDIR)
from shared.version import VERSION  # noqa: E402

# Único dato imprescindible: la CA del servidor (TLS). El icono .ico no se usa en macOS.
datas = [(os.path.join(APPDIR, "shared", "ddt_ca.crt"), "shared")]
binaries = []
hiddenimports = ["services._system_mac", "mss.darwin"]

# customtkinter (temas/datos) y av (decoder H.264 + sus librerías ffmpeg)
for pkg in ("customtkinter", "av"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(APPDIR, "main.py")],
    pathex=[APPDIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Nada de Windows ni del stack de captura/codificación por hardware (el admin solo DECODIFICA con av)
    excludes=["dxcam", "cv2", "opencv-python-headless", "comtypes", "pystray",
              "winreg", "services._system_win", "updater", "win32api", "win32con"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DDT Monitor", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="DDT Monitor")
app = BUNDLE(
    coll,
    name="DDT Monitor.app",
    icon=None,
    bundle_identifier="com.distefano.ddtmonitor",
    info_plist={
        "CFBundleName": "DDT Monitor",
        "CFBundleDisplayName": "DDT Monitor",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Visor de administrador: NO captura la pantalla de la Mac, así que no pide permiso de grabación.
    },
)
