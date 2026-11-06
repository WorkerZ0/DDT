from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import customtkinter as ctk

from components.dialogs import AdminUnlockDialog
from pages.admin import AdminPage
from pages.login import LoginPage
from pages.store import StorePage
from services import session, system
from services.agent import AgentService
from services.bridge import Bridge
from services.tray import Tray
from shared import config, theme

if config.IS_WIN:
    import updater  # tareas programadas / watchdog; solo Windows

log = logging.getLogger("ddt")


def setup_logging() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(config.DATA_DIR / "ddt.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class App(ctk.CTk):
    def __init__(self, autostart: bool):
        super().__init__(fg_color=theme.BG)
        self.title(config.APP_NAME)
        if config.ICON_FILE.exists():
            try:
                self.iconbitmap(str(config.ICON_FILE))  # macOS no acepta .ico: se ignora
            except Exception:
                pass
        self.report_callback_exception = lambda *exc: log.error("error de UI", exc_info=exc)
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)

        self.bridge = Bridge(self)
        self.page = None
        self.agent: AgentService | None = None
        self.tray: Tray | None = None

        saved = session.load()
        if saved and saved.get("user", {}).get("role") == "tienda" and not config.IS_MAC:
            self.start_store(saved["token"], saved["user"], hidden=autostart)
        else:
            self.show_login()

    def _set_page(self, page, width: int, height: int, resizable: bool) -> None:
        if self.page is not None:
            self.page.destroy()
        self.page = page
        page.pack(fill="both", expand=True)
        self.resizable(resizable, resizable)
        scale = self._get_window_scaling()
        x = int((self.winfo_screenwidth() - width * scale) / 2)
        y = int((self.winfo_screenheight() - height * scale) / 3)
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def show_login(self, message: str = "") -> None:
        self.minsize(1, 1)
        self._set_page(LoginPage(self, self.bridge, self.on_login, message), 460, 540, False)
        self.deiconify()

    def on_login(self, token: str, user: dict) -> None:
        if user["role"] == "tienda":
            if config.IS_MAC:  # la versión Mac es solo visor de administrador, no agente de tienda
                self.show_login("La versión para Mac es solo para administradores (ver pantallas).")
                return
            session.save(token, user)
            system.enable_autostart()
            self.start_store(token, user, hidden=False)
        else:
            self.start_admin(token, user)

    # ---------- modo tienda ----------

    def start_store(self, token: str, user: dict, hidden: bool) -> None:
        self._set_page(StorePage(self, user, on_hide=self.on_hide_window), 420, 340, False)
        if self.tray is None and not config.IS_MAC:  # macOS no usa bandeja (conflicto con el hilo principal)
            self.tray = Tray(self.bridge.wrap(self.show_window), self.bridge.wrap(self.request_store_logout),
                             self.bridge.wrap(self.request_store_exit))
            self.tray.start()
        system.clear_stopped()  # el watchdog puede reabrir esta PC si la matan
        if config.IS_MAC:
            system.enable_autostart()  # LaunchAgent (RunAtLoad+KeepAlive): autoarranque y reabrir si lo cierran
        elif config.PORTABLE:
            updater.ensure_user_watchdog()  # Windows portable: watchdog como usuario (sin tarea SYSTEM)
        alert = system.take_killed_alert()  # si el watchdog nos reabrió tras un cierre forzado, avisar al admin
        self.agent = AgentService(token, self.bridge.wrap(self._store_status), self.bridge.wrap(self._store_revoked),
                                  alert=alert)
        self.agent.start()
        self._store_heartbeat()
        log.info("modo tienda: %s en %s", user["username"], config.HOSTNAME)
        if hidden:
            self.on_hide_window()

    def _store_heartbeat(self) -> None:
        if self.agent is None:
            return
        system.write_heartbeat()
        self.after(config.HEARTBEAT_SECONDS * 1000, self._store_heartbeat)

    def _store_status(self, state: str, text: str) -> None:
        if isinstance(self.page, StorePage):
            self.page.set_status(state, text)
        if self.tray:
            self.tray.set_status(state, text)

    def _store_revoked(self) -> None:
        self._stop_store()
        session.clear()
        self.show_login("La sesión de esta PC fue revocada. Ingresa de nuevo con la cuenta de la tienda.")

    def on_hide_window(self) -> None:
        # Windows: a la bandeja. macOS (sin bandeja): minimizar para que siga accesible desde el Dock.
        if config.IS_MAC:
            self.iconify()
        else:
            self.withdraw()

    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def request_store_logout(self) -> None:
        self.show_window()
        AdminUnlockDialog(self, self.bridge, "Para cerrar la sesión de tienda en esta PC se necesita un administrador.",
                          self._store_logout)

    def _store_logout(self) -> None:
        self._stop_store()
        session.clear()
        system.disable_autostart()
        if config.PORTABLE and config.IS_WIN:
            updater.remove_user_watchdog()
        self.show_login()

    def request_store_exit(self) -> None:
        self.show_window()
        AdminUnlockDialog(self, self.bridge, "Para detener la conexión de esta PC se necesita un administrador.",
                          self.quit_app)

    def _stop_store(self) -> None:
        if self.agent:
            self.agent.stop()
            self.agent = None
        if self.tray:
            self.tray.stop()
            self.tray = None

    # ---------- modo admin ----------

    def start_admin(self, token: str, user: dict) -> None:
        self._set_page(AdminPage(self, self.bridge, token, user, self.admin_logout), 1320, 820, True)
        self.minsize(960, 600)
        self.after(50, lambda: self.state("zoomed"))

    def admin_logout(self, message: str = "") -> None:
        if isinstance(self.page, AdminPage):
            self.page.shutdown()
        self.state("normal")
        self.show_login(message)

    # ---------- ventana ----------

    def on_window_close(self) -> None:
        if self.agent:
            self.on_hide_window()  # en modo tienda la X solo oculta
        else:
            self.quit_app()

    def quit_app(self) -> None:
        if isinstance(self.page, AdminPage):
            self.page.shutdown()
        if self.agent is not None:  # cierre autorizado con clave de admin: el watchdog no debe reabrir
            system.mark_stopped()
        self._stop_store()
        self.destroy()


def main() -> None:
    setup_logging()
    autostart = "--autostart" in sys.argv
    if not system.single_instance():
        if not autostart:
            system.message_box(f"{config.APP_NAME} ya está abierto. Búscalo en la bandeja del sistema.")
        return
    ctk.set_appearance_mode("dark")
    App(autostart).mainloop()


if __name__ == "__main__":
    main()
