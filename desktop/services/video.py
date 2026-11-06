"""En vivo como video H.264: captura DXGI (GPU) + codificador por hardware de Media Foundation.

Si la PC no tiene codificador por hardware, `probe()` devuelve False y el agente sigue con JPEG.
Todo se usa desde un único hilo (el de captura del agente). Las librerías pesadas se importan
ahí mismo para que COM quede inicializado en ese hilo.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from fractions import Fraction

log = logging.getLogger("ddt.video")

if sys.platform == "win32":
    from ctypes import wintypes
    # Media Foundation (h264_mf) no funciona con COM en modo STA, que es lo que comtypes (dxcam)
    # inicializa por defecto al importarse.
    sys.coinit_flags = 0

ENCODER_DELAY = 2   # el codificador entrega cada frame 2 frames después: hay que "empujarlo"
KEY_INTERVAL = 2.0  # segundos entre keyframes
_RETRY_SECONDS = 2.0


class _Screen:
    def __init__(self, device, output):
        from dxcam.core import Duplicator, StageSurface
        from dxcam.processor import Processor

        self.device, self.output = device, output
        self.width, self.height = output.resolution
        self.rotation = output.rotation_angle
        rect = output.desc.DesktopCoordinates
        self.left, self.top = rect.left, rect.top
        self.offset = 0
        self.ready = False
        self.stagesurf = StageSurface(output=output, device=device)
        self.duplicator = Duplicator(output=output, device=device)
        self.processor = Processor(output_color="BGRA")

    def grab_into(self, canvas) -> bool:
        """Copia el frame nuevo (imagen o puntero) a su franja del lienzo. Lanza si se perdió el acceso."""
        import numpy as np

        if not self.duplicator.update_frame():
            raise RuntimeError("acceso DXGI perdido")
        if not self.duplicator.updated:
            return False
        self.device.im_context.CopyResource(self.stagesurf.texture, self.duplicator.texture)
        self.duplicator.release_frame()
        rect = self.stagesurf.map()
        try:
            region = canvas[:self.height, self.offset:self.offset + self.width]
            if self.rotation == 0:
                # Una sola copia: de la memoria mapeada de la GPU directo al lienzo
                pitch = int(rect.Pitch)
                address = ctypes.cast(rect.pBits, ctypes.c_void_p).value
                raw = (ctypes.c_ubyte * (pitch * self.height)).from_address(address)
                region[:] = np.frombuffer(raw, np.uint8).reshape(self.height, pitch // 4, 4)[:, :self.width]
            else:
                region[:] = self.processor.process(rect, self.width, self.height,
                                                   (0, 0, self.width, self.height), self.rotation)
        finally:
            self.stagesurf.unmap()
        self.ready = True
        return True

    def release(self) -> None:
        for part in (self.duplicator, self.stagesurf):
            try:
                part.release()
            except Exception:
                pass


class DesktopDuplicator:
    """Todas las pantallas unidas en horizontal sobre un lienzo reutilizado. Reemplaza el manejo de
    errores de dxcam, que se queda en un bucle infinito si la PC está bloqueada o aparece UAC."""

    def __init__(self):
        self.screens: list[_Screen] = []
        self.canvas = None
        self._retry_at = 0.0
        self._under_cursor = None  # (y0, y1, x0, x1, parche) para borrar el puntero dibujado

    def _open(self) -> None:
        import numpy as np
        from dxcam.core import Device, Output
        from dxcam.util.io import enum_dxgi_adapters

        screens = []
        for p_adapter in enum_dxgi_adapters():
            device = Device(p_adapter)
            for p_output in device.enum_outputs():
                screens.append(_Screen(device, Output(p_output)))
        if not screens:
            raise RuntimeError("no hay pantallas DXGI")
        self.screens = sorted(screens, key=lambda s: (s.left, s.top))
        x = 0
        for s in self.screens:
            s.offset = x
            x += s.width
        self.canvas = np.zeros((max(s.height for s in self.screens), x, 4), np.uint8)
        self._under_cursor = None

    def grab(self, force: bool = False):
        """Devuelve (lienzo BGRA, cambió) o (None, False) si no hay nada que enviar.
        El lienzo se reutiliza: usarlo antes de la siguiente llamada."""
        now = time.monotonic()
        if not self.screens:
            if now < self._retry_at:
                return None, False
            try:
                self._open()
            except Exception as exc:
                log.info("DXGI no disponible: %s", exc)
                self.close()
                self._retry_at = now + _RETRY_SECONDS
                return None, False
        self._erase_cursor()
        try:
            changed = False
            for screen in self.screens:
                changed |= screen.grab_into(self.canvas)
        except Exception as exc:
            log.info("DXGI: %s; se reintenta", exc)
            self.close()
            self._retry_at = now + _RETRY_SECONDS
            return None, False
        if not (changed or force) or not all(s.ready for s in self.screens):
            return None, False
        self._draw_cursor()
        return self.canvas, changed

    def _erase_cursor(self) -> None:
        if self._under_cursor is not None:
            y0, y1, x0, x1, patch = self._under_cursor
            self.canvas[y0:y1, x0:x1] = patch
            self._under_cursor = None

    def _draw_cursor(self) -> None:
        import cv2

        pt = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return
        for s in self.screens:
            if s.left <= pt.x < s.left + s.width and s.top <= pt.y < s.top + s.height:
                cx, cy = s.offset + pt.x - s.left, pt.y - s.top
                h, w = self.canvas.shape[:2]
                y0, y1, x0, x1 = max(0, cy - 14), min(h, cy + 15), max(0, cx - 14), min(w, cx + 15)
                self._under_cursor = (y0, y1, x0, x1, self.canvas[y0:y1, x0:x1].copy())
                cv2.circle(self.canvas, (cx, cy), 11, (255, 255, 255, 255), 2, cv2.LINE_AA)
                cv2.circle(self.canvas, (cx, cy), 8, (48, 59, 255, 255), 3, cv2.LINE_AA)
                cv2.circle(self.canvas, (cx, cy), 2, (48, 59, 255, 255), -1, cv2.LINE_AA)
                return

    def close(self) -> None:
        for s in self.screens:
            s.release()
        self.screens = []
        self.canvas = None
        self._under_cursor = None


def _to_nv12(bgra):
    """BGRA -> NV12 (lo que acepta el codificador por hardware). OpenCV es ~3x más rápido que swscale."""
    import cv2
    import numpy as np

    h, w = bgra.shape[:2]
    i420 = cv2.cvtColor(bgra, cv2.COLOR_BGRA2YUV_I420)
    chroma = i420[h:].reshape(-1)
    quarter = chroma.size // 2
    nv12 = np.empty_like(i420)
    nv12[:h] = i420[:h]
    # NV12 = plano Y + U y V intercalados; cv2.merge escribe directo en el buffer de salida
    cv2.merge([chroma[:quarter].reshape(h // 2, w // 2), chroma[quarter:].reshape(h // 2, w // 2)],
              dst=nv12[h:].reshape(h // 2, w // 2, 2))
    return nv12


class H264Encoder:
    def __init__(self):
        self._ctx = None
        self._size = None
        self._pts = 0
        self._last_nv12 = None

    def _open(self, width: int, height: int, fps: int, bitrate: int) -> None:
        import av

        ctx = av.CodecContext.create("h264_mf", "w")
        ctx.width, ctx.height, ctx.pix_fmt = width, height, "nv12"
        ctx.time_base = Fraction(1, fps)
        ctx.framerate = Fraction(fps, 1)
        ctx.bit_rate = int(bitrate * width * height / (1920 * 1080))
        ctx.gop_size = int(fps * KEY_INTERVAL)
        ctx.max_b_frames = 0
        # hw_encoding=1: falla si no hay codificador por hardware (no cae a software en silencio)
        ctx.options = {"hw_encoding": "1", "scenario": "display_remoting", "rate_control": "cbr"}
        ctx.open()
        self._ctx, self._size, self._pts = ctx, (width, height), 0

    def encode(self, bgra, force_key: bool, fps: int, bitrate: int, max_height: int = 1080):
        """Codifica una imagen BGRA (o repite la última si bgra es None). Devuelve [(es_keyframe, bytes)]."""
        import av
        import cv2

        if bgra is not None:
            h, w = bgra.shape[:2]
            scale = min(1.0, max_height / h, 4096 / w)
            tw, th = int(w * scale) & ~1, int(h * scale) & ~1  # 4:2:0 exige medidas pares
            if (tw, th) != (w, h):
                bgra = cv2.resize(bgra, (tw, th), interpolation=cv2.INTER_AREA) if scale < 1 else bgra[:th, :tw]
            if self._size != (tw, th):
                self.close()
                self._open(tw, th, fps, bitrate)
                force_key = True
            self._last_nv12 = _to_nv12(bgra)
        if self._ctx is None or self._last_nv12 is None:
            return []
        frame = av.VideoFrame.from_ndarray(self._last_nv12, format="nv12")
        frame.pts = self._pts
        self._pts += 1
        if force_key:
            frame.pict_type = av.video.frame.PictureType.I
        return [(bool(p.is_keyframe), bytes(p)) for p in self._ctx.encode(frame)]

    def close(self) -> None:
        self._ctx = None
        self._size = None
        self._last_nv12 = None


def probe() -> bool:
    """¿Esta PC puede transmitir video? (codificador H.264 por hardware + captura DXGI)."""
    try:
        import numpy as np

        enc = H264Encoder()
        packets = []
        for i in range(ENCODER_DELAY + 3):
            packets += enc.encode(np.zeros((360, 640, 4), np.uint8), i == 0, 25, 1_000_000)
        enc.close()
        if not packets:
            log.info("codificador por hardware sin salida")
            return False
        dup = DesktopDuplicator()
        dup._open()
        dup.close()
        log.info("video H.264 por hardware disponible")
        return True
    except Exception as exc:
        log.info("sin video por hardware (%s): se usa JPEG", exc)
        return False
