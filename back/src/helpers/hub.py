"""Relay en memoria: agentes (PCs de tienda) -> visores (admins).

Frames binarios:
  agente -> server : [1 byte tipo][datos]
  server -> visor  : [1 byte tipo][4 bytes device_id big-endian][datos]
tipo 0 = miniatura JPEG (siempre, cada THUMB_INTERVAL)
tipo 1 = en vivo JPEG (PCs sin codificador por hardware)
tipo 2/3 = en vivo H.264 (2 = frame delta, 3 = keyframe). Van en orden: perder uno rompe la imagen
           hasta el siguiente keyframe.
Texto agente -> server: {"type": "activity", "idle": segundos sin teclado/mouse}
"""
import asyncio
import json
import logging
import struct
import time

from fastapi import WebSocket

from src.config import settings
from src.helpers import repo

log = logging.getLogger("ddt.hub")

KIND_THUMB, KIND_LIVE, KIND_VIDEO, KIND_VIDEO_KEY = 0, 1, 2, 3
_HEADER = struct.Struct(">BI")
MAX_VIDEO_BACKLOG = 60  # paquetes (~2,5 s a 25 fps) antes de descartar y pedir keyframe


async def close_ws(ws: WebSocket, code: int, reason: str = "") -> None:
    try:
        await ws.close(code, reason)
    except Exception:
        pass


_closing: set[asyncio.Task] = set()


def close_later(ws: WebSocket, code: int, reason: str = "") -> None:
    """Cierra sin esperar el handshake: un cliente lento no debe frenar la API."""
    task = asyncio.create_task(close_ws(ws, code, reason))
    _closing.add(task)
    task.add_done_callback(_closing.discard)


class Agent:
    def __init__(self, ws: WebSocket, user: dict, device_id: int, hostname: str, video: bool, version: str = ""):
        self.ws = ws
        self.user_id = user["id"]
        self.device_id = device_id
        self.hostname = hostname
        self.video = video  # el agente tiene codificador H.264 por hardware
        self.version = version  # versión del cliente (vacía en clientes < 1.3.0)
        self.thumb_width = settings.THUMB_WIDTH  # el mayor que pide algún visor que la tiene en pantalla
        self.watchers: set["Viewer"] = set()
        self.last_thumb: bytes | None = None
        self.live = False
        self.active_at: float | None = None  # time.monotonic() del último teclado/mouse
        self._lock = asyncio.Lock()

    def idle(self) -> float | None:
        return None if self.active_at is None else round(time.monotonic() - self.active_at, 1)

    def config(self) -> dict:
        return {
            "type": "config",
            "live": self.live,
            "thumb_interval": settings.THUMB_INTERVAL,
            "thumb_width": self.thumb_width,
            "thumb_quality": settings.THUMB_QUALITY if self.thumb_width <= settings.THUMB_WIDTH
            else settings.THUMB_HD_QUALITY,
            "live_fps": settings.LIVE_FPS,
            "live_width": settings.LIVE_WIDTH,
            "live_height": settings.LIVE_HEIGHT,
            "live_quality": settings.LIVE_QUALITY,
            "video": settings.VIDEO_ENABLED,
            "video_fps": settings.VIDEO_FPS,
            "video_bitrate": settings.VIDEO_BITRATE,
        }

    async def send_json(self, msg: dict) -> None:
        async with self._lock:
            try:
                await self.ws.send_json(msg)
            except Exception:
                pass

    async def send_config(self) -> None:
        await self.send_json(self.config())


class Viewer:
    """Miniaturas y JPEG: "último gana" (si va lento se descartan los viejos).
    Video: cola en orden; si se atrasa demasiado se vacía y se espera el siguiente keyframe."""

    def __init__(self, ws: WebSocket, user: dict):
        self.ws = ws
        self.user_id = user["id"]
        self.watching: int | None = None
        self.thumb_width = 0               # ancho en px de sus tarjetas (0 = visor viejo, usa el default)
        self.visible: set[int] = set()     # PCs que tiene en pantalla
        self.need_key = True
        self._texts: list[str] = []
        self._frames: dict[tuple[int, int], bytes] = {}
        self._video: list[bytes] = []
        self._wake = asyncio.Event()

    def send_json(self, obj: dict) -> None:
        self._texts.append(json.dumps(obj))
        self._wake.set()

    def send_frame(self, kind: int, device_id: int, data: bytes) -> None:
        self._frames[(kind, device_id)] = _HEADER.pack(kind, device_id) + data
        self._wake.set()

    def send_video(self, kind: int, device_id: int, data: bytes) -> bool:
        """Devuelve False si hay que pedirle un keyframe al agente."""
        if self.need_key:
            if kind != KIND_VIDEO_KEY:
                return False
            self.need_key = False
        if len(self._video) >= MAX_VIDEO_BACKLOG:
            self._video.clear()
            self.need_key = True
            return False
        self._video.append(_HEADER.pack(kind, device_id) + data)
        self._wake.set()
        return True

    def reset_video(self) -> None:
        self._video.clear()
        self.need_key = True

    async def pump(self) -> None:
        try:
            while True:
                await self._wake.wait()
                self._wake.clear()
                texts, self._texts = self._texts, []
                frames, self._frames = self._frames, {}
                video, self._video = self._video, []
                for text in texts:
                    await self.ws.send_text(text)
                for packet in video:
                    await self.ws.send_bytes(packet)
                for frame in frames.values():
                    await self.ws.send_bytes(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            await close_ws(self.ws, 1011)


class Hub:
    def __init__(self):
        self.agents: dict[int, Agent] = {}
        self.viewers: set[Viewer] = set()
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---------- agentes ----------

    async def add_agent(self, agent: Agent) -> None:
        old = self.agents.get(agent.device_id)
        if old:
            close_later(old.ws, 4409, "Reemplazado por otra conexión")
        self.agents[agent.device_id] = agent
        agent.watchers = {v for v in self.viewers if v.watching == agent.device_id}
        for viewer in agent.watchers:
            viewer.reset_video()
        agent.live = bool(agent.watchers)
        agent.thumb_width = self._wanted_thumb(agent)
        await agent.send_config()
        log.info("Agente conectado device=%s host=%s video=%s", agent.device_id, agent.hostname, agent.video)
        self.broadcast_devices()

    def remove_agent(self, agent: Agent) -> None:
        if self.agents.get(agent.device_id) is not agent:
            return
        del self.agents[agent.device_id]
        repo.touch_device(agent.device_id)
        log.info("Agente desconectado device=%s", agent.device_id)
        self.broadcast_devices()

    def on_frame(self, agent: Agent, data: bytes) -> None:
        if len(data) < 2 or len(data) > settings.MAX_FRAME_BYTES:
            return
        kind, payload = data[0], data[1:]
        if kind == KIND_THUMB:
            agent.last_thumb = payload
            for viewer in self.viewers:
                viewer.send_frame(KIND_THUMB, agent.device_id, payload)
        elif kind == KIND_LIVE and agent.live:
            for viewer in agent.watchers:
                viewer.send_frame(KIND_LIVE, agent.device_id, payload)
        elif kind in (KIND_VIDEO, KIND_VIDEO_KEY) and agent.live:
            if not all([v.send_video(kind, agent.device_id, payload) for v in agent.watchers]):
                self.request_keyframe(agent)

    def on_text(self, agent: Agent, msg: dict) -> None:
        if msg.get("type") == "activity" and isinstance(msg.get("idle"), (int, float)):
            agent.active_at = time.monotonic() - max(0.0, float(msg["idle"]))
            update = {"type": "activity", "device_id": agent.device_id, "idle": agent.idle()}
            for viewer in self.viewers:
                viewer.send_json(update)

    def request_keyframe(self, agent: Agent) -> None:
        if agent.video:
            self._spawn(agent.send_json({"type": "keyframe"}))

    def request_update(self, viewer: Viewer, device_ids: set[int]) -> None:
        """El admin pide "Actualizar ahora". El agente solo deja una marca; el actualizador (SYSTEM)
        verifica la firma, así que esto no permite instalar nada que no esté firmado."""
        sent = [d for d in device_ids if d in self.agents]
        for device_id in sent:
            self._spawn(self.agents[device_id].send_json({"type": "update_now"}))
        log.info("Actualizar ahora: user=%s devices=%s", viewer.user_id, sorted(sent))

    def announce_alert(self, agent: Agent, event: str, at: int) -> None:
        """Aviso del agente (p. ej. lo cerraron a la fuerza y el watchdog lo reabrió)."""
        log.warning("ALERTA device=%s host=%s evento=%s", agent.device_id, agent.hostname, event)
        msg = {"type": "alert", "device_id": agent.device_id, "hostname": agent.hostname,
               "event": event, "at": at}
        for viewer in self.viewers:
            viewer.send_json(msg)

    # ---------- visores ----------

    def add_viewer(self, viewer: Viewer) -> None:
        self.viewers.add(viewer)
        viewer.send_json({"type": "devices", "devices": self.device_list()})
        for agent in self.agents.values():
            if agent.last_thumb:
                viewer.send_frame(KIND_THUMB, agent.device_id, agent.last_thumb)

    async def remove_viewer(self, viewer: Viewer) -> None:
        self.viewers.discard(viewer)
        await self.set_watch(viewer, None)
        self.set_view(viewer, 0, set())

    def set_view(self, viewer: Viewer, thumb_width: int, visible: set[int]) -> None:
        """El visor avisa qué PCs tiene en pantalla y a qué ancho: la miniatura se pide a ese tamaño.

        Como las tarjetas se achican cuando hay más PCs, el total de píxeles queda acotado por la pantalla.
        """
        affected = viewer.visible | visible
        viewer.thumb_width, viewer.visible = thumb_width, visible
        for device_id in affected:
            agent = self.agents.get(device_id)
            if agent:
                width = self._wanted_thumb(agent)
                if width != agent.thumb_width:
                    agent.thumb_width = width
                    self._spawn(agent.send_config())

    def _wanted_thumb(self, agent: Agent) -> int:
        wanted = max((v.thumb_width for v in self.viewers if agent.device_id in v.visible), default=0)
        return min(max(wanted, settings.THUMB_WIDTH), settings.THUMB_MAX_WIDTH)

    async def set_watch(self, viewer: Viewer, device_id: int | None) -> None:
        prev = viewer.watching
        if prev == device_id:
            return
        viewer.watching = device_id
        viewer.reset_video()
        if prev is not None and (agent := self.agents.get(prev)):
            agent.watchers.discard(viewer)
            await self._sync_live(agent)
        if device_id is not None and (agent := self.agents.get(device_id)):
            agent.watchers.add(viewer)
            if agent.live:
                self.request_keyframe(agent)  # ya transmitía: el visor nuevo necesita un keyframe
            await self._sync_live(agent)

    async def _sync_live(self, agent: Agent) -> None:
        live = bool(agent.watchers)
        if live != agent.live:
            agent.live = live
            await agent.send_config()

    # ---------- estado ----------

    def device_list(self) -> list[dict]:
        devices = []
        for row in repo.list_devices():
            agent = self.agents.get(row["id"])
            devices.append({
                "id": row["id"],
                "hostname": row["hostname"],
                "user_id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "last_seen": row["last_seen"],
                "online": agent is not None,
                "live": bool(agent and agent.live),
                "watchers": len(agent.watchers) if agent else 0,
                "video": bool(agent and agent.video),
                "version": agent.version if agent else "",
                "idle": agent.idle() if agent else None,
            })
        return devices

    def broadcast_devices(self) -> None:
        if not self.viewers:
            return
        msg = {"type": "devices", "devices": self.device_list()}
        for viewer in self.viewers:
            viewer.send_json(msg)

    def disconnect_user(self, user_id: int) -> None:
        for agent in [a for a in self.agents.values() if a.user_id == user_id]:
            close_later(agent.ws, 4401, "Sesión revocada")
        for viewer in [v for v in self.viewers if v.user_id == user_id]:
            close_later(viewer.ws, 4401, "Sesión revocada")

    def disconnect_device(self, device_id: int) -> None:
        if agent := self.agents.get(device_id):
            close_later(agent.ws, 4410, "Dispositivo eliminado")


hub = Hub()
