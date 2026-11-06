from shared import config, theme
from shared.logo import draw_logo

_STATUS_DOT = {
    "online": theme.ONLINE,
    "live": theme.LIVE,
    "connecting": theme.WARN,
    "offline": theme.OFFLINE,
    "error": theme.DANGER,
}


class Tray:
    """Icono de bandeja. Las acciones llegan desde el hilo de pystray: pasarlas envueltas con Bridge.wrap."""

    def __init__(self, on_show, on_logout, on_exit):
        import pystray  # perezoso: solo Windows instancia la bandeja (macOS no la usa)

        menu = pystray.Menu(
            pystray.MenuItem("Ver estado", lambda: on_show(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar sesión de tienda…", lambda: on_logout()),
            pystray.MenuItem("Salir…", lambda: on_exit()),
        )
        self._icon = pystray.Icon(config.APP_ID, draw_logo(64, theme.WARN), config.APP_NAME, menu)

    def start(self) -> None:
        self._icon.run_detached()

    def set_status(self, state: str, text: str) -> None:
        self._icon.icon = draw_logo(64, _STATUS_DOT.get(state, theme.OFFLINE))
        self._icon.title = f"{config.APP_NAME} — {text}"[:127]

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
