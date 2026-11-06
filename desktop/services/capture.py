from __future__ import annotations

import ctypes
import io
import logging
import sys
import time

import mss
from PIL import Image, ImageDraw

if sys.platform == "win32":
    from ctypes import wintypes

log = logging.getLogger("ddt.capture")

_REFRESH_SECONDS = 60  # recrea mss para detectar monitores conectados/desconectados


class Capturer:
    """Captura todos los monitores en una sola imagen. Usar siempre desde el mismo hilo."""

    def __init__(self):
        self._sct = None
        self._created = 0.0

    def grab(self) -> Image.Image | None:
        try:
            if self._sct is None or time.monotonic() - self._created > _REFRESH_SECONDS:
                self.close()
                self._sct = mss.mss()
                self._created = time.monotonic()
            area = self._sct.monitors[0]
            shot = self._sct.grab(area)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            _draw_cursor(img, area["left"], area["top"])
            return img
        except Exception as exc:
            # Pasa con la pantalla bloqueada o el escritorio seguro de UAC
            log.debug("captura falló: %s", exc)
            self.close()
            return None

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


def _draw_cursor(img: Image.Image, left: int, top: int) -> None:
    """La captura de Windows no incluye el puntero: se marca con un anillo para ver dónde actúa el usuario."""
    if sys.platform != "win32":
        return  # en macOS la captura de mss ya incluye el puntero
    pt = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return
    x, y = pt.x - left, pt.y - top
    if not (0 <= x < img.width and 0 <= y < img.height):
        return
    d = ImageDraw.Draw(img)
    d.ellipse((x - 11, y - 11, x + 11, y + 11), outline=(255, 255, 255), width=2)
    d.ellipse((x - 9, y - 9, x + 9, y + 9), outline=(255, 59, 48), width=3)
    d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 59, 48))


def encode(img: Image.Image, max_width: int, quality: int, max_height: int | None = None) -> bytes:
    scale = min(1.0, max_width / img.width, (max_height or img.height) / img.height)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
