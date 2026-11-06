from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import struct
import threading

from PIL import Image

from services.connection import WsService
from shared import config

KIND_THUMB, KIND_LIVE, KIND_VIDEO, KIND_VIDEO_KEY = 0, 1, 2, 3
_HEADER = struct.Struct(">BI")

# El runtime de Windows 7 (Python 3.8, 32 bits) no trae PyAV: ahí no se puede ver video H.264
CAN_DECODE_VIDEO = importlib.util.find_spec("av") is not None


def _decode(data: bytes) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        return None


class ViewerService(WsService):
    """Recibe lista de PCs, actividad y frames. La UI recoge los frames con take_frames() (último gana).

    El video en vivo se decodifica aquí, en orden, y se entrega ya escalado a `display_box`.
    """

    path = "/ws/viewer"

    def __init__(self, token: str, on_devices, on_activity, on_status, on_auth_error, on_alert=None):
        super().__init__(token, config.WS_SERVER, config.SSL_CTX, on_status, on_auth_error)
        self.on_devices = on_devices
        self.on_activity = on_activity
        self.on_alert = on_alert
        self.display_box = (1280, 720)  # píxeles disponibles donde se ve el en vivo (ventana o tarjeta)
        self._frames: dict[tuple[int, int], Image.Image] = {}
        self._lock = threading.Lock()
        self._ws = None
        self._watching: int | None = None
        self._view: dict | None = None
        self._decoder = None
        self._decoder_device: int | None = None

    def take_frames(self) -> dict[tuple[int, int], Image.Image]:
        with self._lock:
            frames, self._frames = self._frames, {}
        return frames

    def watch(self, device_id: int | None) -> None:
        self._watching = device_id
        msg = {"type": "watch", "device_id": device_id} if device_id is not None else {"type": "unwatch"}
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)

    def request_update(self, device_ids: list[int]) -> None:
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._send({"type": "update_now", "device_ids": device_ids}), self._loop)

    def set_view(self, thumb_width: int, device_ids: list[int]) -> None:
        """PCs en pantalla y ancho (px reales) de sus tarjetas: el server pide miniaturas a ese tamaño."""
        msg = {"type": "view", "thumb_width": thumb_width, "device_ids": device_ids}
        if msg == self._view:
            return
        self._view = msg
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)

    async def _send(self, msg: dict) -> None:
        try:
            await self._ws.send(json.dumps(msg))
        except Exception:
            pass

    def _decode_video(self, device_id: int, key: bool, data: bytes) -> Image.Image | None:
        import av

        if self._decoder_device != device_id:
            self._decoder, self._decoder_device = None, device_id
        if self._decoder is None:
            if not key:
                return None  # sin keyframe no se puede empezar a decodificar
            self._decoder = av.CodecContext.create("h264", "r")
        try:
            frames = self._decoder.decode(av.Packet(data))
        except av.error.FFmpegError:
            self._decoder = None
            return None
        if not frames:
            return None
        frame = frames[-1]
        box_w, box_h = self.display_box
        scale = min(box_w / frame.width, box_h / frame.height)
        width, height = max(2, int(frame.width * scale)), max(2, int(frame.height * scale))
        return frame.to_image(width=width, height=height)

    async def _session(self, ws) -> None:
        loop = asyncio.get_running_loop()
        await ws.send(json.dumps({"type": "auth", "token": self.token}))
        self._ws = ws
        self._decoder = None
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "ready":
                        self._connected = True
                        self.on_status("online", "Conectado")
                        if self._watching is not None:
                            await self._send({"type": "watch", "device_id": self._watching})
                        if self._view is not None:
                            await self._send(self._view)
                    elif kind == "devices":
                        self.on_devices(msg["devices"])
                    elif kind == "activity":
                        self.on_activity(msg["device_id"], msg["idle"])
                    elif kind == "alert" and self.on_alert:
                        self.on_alert(msg)
                    continue
                if len(raw) <= _HEADER.size:
                    continue
                kind, device_id = _HEADER.unpack_from(raw)
                payload = raw[_HEADER.size:]
                if kind in (KIND_VIDEO, KIND_VIDEO_KEY):
                    if device_id != self._watching or not CAN_DECODE_VIDEO:
                        continue
                    img = await loop.run_in_executor(None, self._decode_video, device_id,
                                                     kind == KIND_VIDEO_KEY, payload)
                    kind = KIND_LIVE
                else:
                    img = await loop.run_in_executor(None, _decode, payload)
                if img is not None:
                    with self._lock:
                        self._frames[(kind, device_id)] = img
        finally:
            self._ws = None
