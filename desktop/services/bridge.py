import logging
import queue
import threading

log = logging.getLogger("ddt.bridge")


class Bridge:
    """Lleva llamadas desde hilos de fondo al hilo de Tk (Tk no es thread-safe)."""

    def __init__(self, root, interval_ms: int = 40):
        self._root = root
        self._interval = interval_ms
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._tick()

    def post(self, fn, *args) -> None:
        self._queue.put((fn, args))

    def wrap(self, fn):
        """Devuelve una versión de fn que se puede llamar desde cualquier hilo."""
        return lambda *args: self.post(fn, *args)

    def run_bg(self, fn, on_ok=None, on_err=None) -> None:
        def work():
            try:
                result = fn()
            except Exception as exc:
                log.warning("tarea en segundo plano falló: %s", exc)
                if on_err:
                    self.post(on_err, exc)
                return
            if on_ok:
                self.post(on_ok, result)

        threading.Thread(target=work, daemon=True).start()

    def _tick(self) -> None:
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                log.exception("error en callback de UI")
        self._root.after(self._interval, self._tick)
