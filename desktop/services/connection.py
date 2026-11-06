from __future__ import annotations

import asyncio
import logging
import threading

import websockets
from websockets.asyncio.client import connect  # misma API en websockets 13 (Win7/py3.8) y 14

log = logging.getLogger("ddt.ws")

AUTH_CLOSE_CODES = {4401, 4403}


class WsService:
    """Base: loop asyncio en hilo propio con reconexión exponencial.

    Las subclases implementan `_session(ws)`. Los callbacks se llaman desde el hilo
    de fondo: el que los pasa debe envolverlos con Bridge.wrap.
    """

    path = ""

    def __init__(self, token: str, url: str, ssl_ctx, on_status, on_auth_error):
        self.token = token
        self._url = url + self.path
        self._ssl = ssl_ctx
        self.on_status = on_status
        self.on_auth_error = on_auth_error
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._connected = False

    def start(self) -> None:
        threading.Thread(target=self._run, name=type(self).__name__, daemon=True).start()

    def stop(self) -> None:
        if self._loop and self._task and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:  # el loop terminó entre el chequeo y la llamada
                pass

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._task = self._loop.create_task(self._main())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        finally:
            self._cleanup()
            self._loop.close()

    def _cleanup(self) -> None:
        pass

    async def _main(self) -> None:
        delay = 1
        while True:
            self._connected = False
            self.on_status("connecting", "Conectando…")
            try:
                async with connect(self._url, ssl=self._ssl, open_timeout=15, ping_interval=20,
                                   ping_timeout=20, max_size=4 * 1024 * 1024) as ws:
                    await self._session(ws)
                self.on_status("offline", "Conexión cerrada, reintentando…")
            except websockets.ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                if code in AUTH_CLOSE_CODES:
                    self.on_status("error", "Sesión inválida o revocada")
                    self.on_auth_error()
                    return
                if code == 4409:
                    self.on_status("offline", "Otra conexión usa este nombre de PC, reintentando…")
                else:
                    self.on_status("offline", "Conexión perdida, reintentando…")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("%s: %s", type(self).__name__, exc)
                self.on_status("offline", "Sin conexión con el servidor, reintentando…")
            if self._connected:
                delay = 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _session(self, ws) -> None:
        raise NotImplementedError
