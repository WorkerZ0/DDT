from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

from services import video
from services.capture import Capturer, encode
from services.connection import WsService
from services.system import input_idle_seconds, request_update
from shared import config
from shared.version import VERSION

KIND_THUMB, KIND_LIVE, KIND_VIDEO, KIND_VIDEO_KEY = 0, 1, 2, 3
LIVE_KEEPALIVE = 2.0
MAX_CPU_SHARE = 0.4  # fracción máxima de un núcleo para capturar y codificar en vivo


class AgentService(WsService):
    """Transmite la pantalla: miniatura cada thumb_interval y, si un admin mira, en vivo.

    En vivo usa video H.264 si la PC tiene codificador por hardware; si no, JPEG a live_fps.
    """

    path = "/ws/agent"

    def __init__(self, token: str, on_status, on_auth_error, alert: dict | None = None):
        super().__init__(token, config.WS_SERVER, config.SSL_CTX, on_status, on_auth_error)
        self._alert = alert  # aviso de "cierre forzado" para el admin; se manda una vez al autenticar
        # mss, DXGI y Media Foundation exigen usarse siempre desde el mismo hilo
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
        self._capturer = Capturer()
        self._video_ok: bool | None = None
        self._dup: video.DesktopDuplicator | None = None
        self._enc: video.H264Encoder | None = None
        self._tail = 0
        self._cpu = 0.0  # segundos de CPU del último trabajo de captura

    def _cleanup(self) -> None:
        self._pool.submit(self._capturer.close)
        self._pool.submit(self._video_stop)
        self._pool.shutdown(wait=False)

    # ---------- en el hilo de captura ----------

    def _capture(self, live: bool, thumb: bool, cfg: dict) -> list[tuple[int, bytes]]:
        started = time.thread_time()
        try:
            return self._capture_jpeg(live, thumb, cfg)
        finally:
            self._cpu = time.thread_time() - started

    def _capture_jpeg(self, live: bool, thumb: bool, cfg: dict) -> list[tuple[int, bytes]]:
        img = self._capturer.grab()
        if img is None:
            return []
        frames = []
        if live:
            frames.append((KIND_LIVE, encode(img, cfg["live_width"], cfg["live_quality"], cfg["live_height"])))
        if thumb:
            frames.append((KIND_THUMB, encode(img, cfg["thumb_width"], cfg["thumb_quality"])))
        return frames

    def _video_tick(self, cfg: dict, force_key: bool) -> list[tuple[int, bytes]]:
        started = time.thread_time()
        try:
            return self._video_frame(cfg, force_key)
        finally:
            self._cpu = time.thread_time() - started

    def _video_frame(self, cfg: dict, force_key: bool) -> list[tuple[int, bytes]]:
        if self._dup is None:
            self._dup, self._enc = video.DesktopDuplicator(), video.H264Encoder()
        fps, bitrate = int(cfg["video_fps"]), int(cfg["video_bitrate"])
        img, _changed = self._dup.grab(force=force_key)
        if img is not None:
            self._tail = video.ENCODER_DELAY
            packets = self._enc.encode(img, force_key, fps, bitrate, cfg["live_height"])
        elif self._tail > 0:
            # Pantalla quieta: se repite el último frame para que el codificador entregue lo pendiente
            self._tail -= 1
            packets = self._enc.encode(None, False, fps, bitrate)
        else:
            return []
        return [(KIND_VIDEO_KEY if key else KIND_VIDEO, data) for key, data in packets]

    def _video_stop(self) -> None:
        if self._dup:
            self._dup.close()
        if self._enc:
            self._enc.close()
        self._dup = self._enc = None
        self._tail = 0

    # ---------- loop ----------

    async def _session(self, ws) -> None:
        loop = asyncio.get_running_loop()
        if self._video_ok is None:
            self._video_ok = await loop.run_in_executor(self._pool, video.probe)
        auth = {"type": "auth", "token": self.token, "hostname": config.HOSTNAME,
                "video": self._video_ok, "version": VERSION}
        if self._alert:
            auth["alert"] = self._alert
            self._alert = None  # no reenviar en reconexiones
        await ws.send(json.dumps(auth))
        cfg = {"live": False, "thumb_interval": 5.0, "thumb_width": 480, "thumb_quality": 40,
               "live_fps": 8.0, "live_width": 3840, "live_height": 1080, "live_quality": 50,
               "video": True, "video_fps": 25, "video_bitrate": 2_500_000}
        changed = asyncio.Event()
        state = {"key": False, "thumb": False}

        async def reader():
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "ready":
                    self._connected = True
                elif kind == "update_now":
                    request_update()  # el watchdog (SYSTEM) corre el actualizador en su próxima vuelta
                elif kind == "keyframe":
                    state["key"] = True
                elif kind == "config":
                    if msg.get("thumb_width", cfg["thumb_width"]) != cfg["thumb_width"]:
                        state["thumb"] = True  # el admin agrandó la tarjeta: miniatura nítida ya, sin esperar
                    cfg.update({k: v for k, v in msg.items() if k in cfg})
                    changed.set()
                    if cfg["live"]:
                        self.on_status("live", "Conectado a la Red")
                    else:
                        self.on_status("online", "Conectado a la Red")

        reader_task = asyncio.create_task(reader())
        next_thumb = 0.0
        last_live, last_live_at = b"", 0.0
        video_active = False
        try:
            while not reader_task.done():
                start = loop.time()
                live = cfg["live"]
                use_video = live and cfg["video"] and self._video_ok
                want_thumb = start >= next_thumb or state.pop("thumb", False)
                if video_active and not use_video:
                    await loop.run_in_executor(self._pool, self._video_stop)
                    video_active = False
                if not live:
                    last_live = b""

                if self._connected and (want_thumb or (live and not use_video)):
                    jpeg_live = live and not use_video
                    frames = await loop.run_in_executor(self._pool, self._capture, jpeg_live, want_thumb, dict(cfg))
                    for kind, data in frames:
                        if kind == KIND_LIVE:
                            # Pantalla quieta = mismo JPEG: no se reenvía (refresco cada KEEPALIVE para visores nuevos)
                            if data == last_live and start - last_live_at < LIVE_KEEPALIVE:
                                continue
                            last_live, last_live_at = data, start
                        await ws.send(bytes([kind]) + data)
                    if want_thumb:
                        next_thumb = start + cfg["thumb_interval"]
                        idle = input_idle_seconds()
                        if idle is not None:
                            await ws.send(json.dumps({"type": "activity", "idle": round(idle, 1)}))

                if self._connected and use_video:
                    force_key = state["key"] or not video_active
                    state["key"] = False
                    video_active = True
                    packets = await loop.run_in_executor(self._pool, self._video_tick, dict(cfg), force_key)
                    for kind, data in packets:
                        await ws.send(bytes([kind]) + data)

                if live:
                    fps = cfg["video_fps"] if use_video else cfg["live_fps"]
                    # En PCs lentas se bajan los fps solos: como máximo ~40% de un núcleo en captura
                    period = max(1 / max(fps, 0.1), self._cpu / MAX_CPU_SHARE)
                    wait = period - (loop.time() - start)
                else:
                    wait = max(next_thumb - loop.time(), 0.05)
                if wait > 0:
                    # Despierta antes si cambia la config o se cae la conexión
                    waiter = asyncio.ensure_future(changed.wait())
                    try:
                        await asyncio.wait({waiter, reader_task}, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        waiter.cancel()
                changed.clear()
            await reader_task  # propaga ConnectionClosed con su código
        finally:
            reader_task.cancel()
            if video_active:
                self._pool.submit(self._video_stop)
