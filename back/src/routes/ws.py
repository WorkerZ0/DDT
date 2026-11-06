import asyncio
import json

from fastapi import APIRouter, WebSocket

from src.config import settings
from src.helpers import repo
from src.helpers.hub import Agent, Viewer, close_ws, hub
from src.middlewares.auth import user_from_token

router = APIRouter()


async def _authenticate(ws: WebSocket, role: str) -> tuple[dict, dict] | None:
    """Primer mensaje: {"type": "auth", "token": "...", ...}."""
    try:
        msg = json.loads(await asyncio.wait_for(ws.receive_text(), settings.WS_AUTH_TIMEOUT))
        user = user_from_token(str(msg["token"])) if msg.get("type") == "auth" else None
    except Exception:
        await close_ws(ws, 4400, "Auth inválida")
        return None
    if not user:
        await close_ws(ws, 4401, "Sesión inválida o expirada")
        return None
    if user["role"] != role:
        await close_ws(ws, 4403, "Rol no permitido")
        return None
    return user, msg


async def _messages(ws: WebSocket):
    while True:
        try:
            msg = await ws.receive()
        except RuntimeError:
            return
        if msg["type"] == "websocket.disconnect":
            return
        yield msg


@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket):
    await ws.accept()
    auth = await _authenticate(ws, "tienda")
    if not auth:
        return
    user, msg = auth
    hostname = str(msg.get("hostname", "")).strip()[:64]
    if not hostname:
        await close_ws(ws, 4400, "Falta hostname")
        return

    device_id = repo.upsert_device(user["id"], hostname)
    version = str(msg.get("version", ""))[:16]
    agent = Agent(ws, user, device_id, hostname, video=msg.get("video") is True, version=version)
    await ws.send_json({"type": "ready", "device_id": device_id})
    await hub.add_agent(agent)
    alert = msg.get("alert")
    if isinstance(alert, dict) and alert.get("event") == "terminated":
        at = alert.get("at")
        hub.announce_alert(agent, "terminated", int(at) if isinstance(at, (int, float)) else 0)
    try:
        async for m in _messages(ws):
            if (data := m.get("bytes")) is not None:
                hub.on_frame(agent, data)
            elif text := m.get("text"):
                try:
                    hub.on_text(agent, json.loads(text))
                except (ValueError, AttributeError):
                    pass
    finally:
        hub.remove_agent(agent)


@router.websocket("/ws/viewer")
async def viewer_ws(ws: WebSocket):
    await ws.accept()
    auth = await _authenticate(ws, "admin")
    if not auth:
        return
    user, _ = auth

    await ws.send_json({"type": "ready"})
    viewer = Viewer(ws, user)
    pump = asyncio.create_task(viewer.pump())
    hub.add_viewer(viewer)
    try:
        async for m in _messages(ws):
            try:
                data = json.loads(m.get("text") or "")
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "watch" and isinstance(data.get("device_id"), int):
                await hub.set_watch(viewer, data["device_id"])
            elif kind == "unwatch":
                await hub.set_watch(viewer, None)
            elif kind == "update_now" and isinstance(data.get("device_ids"), list):
                ids = {i for i in data["device_ids"][:1000] if isinstance(i, int)}
                hub.request_update(viewer, ids)
            elif kind == "view" and isinstance(data.get("thumb_width"), int) and isinstance(data.get("device_ids"), list):
                # Redondeado a múltiplos de 160 px para no reconfigurar agentes en cada pixel de resize
                width = -(-max(0, data["thumb_width"]) // 160) * 160
                ids = {i for i in data["device_ids"][:1000] if isinstance(i, int)}
                hub.set_view(viewer, width, ids)
    finally:
        pump.cancel()
        await hub.remove_viewer(viewer)
