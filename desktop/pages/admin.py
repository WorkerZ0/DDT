from __future__ import annotations

import json
import math
import time
import tkinter as tk
from datetime import datetime

import customtkinter as ctk
from customtkinter.windows.widgets.scaling import ScalingTracker

from components.dialogs import ConfirmDialog
from components.tile import ScreenTile, device_name
from pages.live import LiveWindow
from pages.users import UsersPanel
from services.api import Api, ApiError
from services.viewer import KIND_LIVE, KIND_THUMB, ViewerService
from shared import config, theme
from shared.logo import draw_logo

GAP = 12
MIN_TILE = 250
MAX_TILE = 980
ALL_STORES = "Todas las tiendas"
SORT_STORE, SORT_ACTIVITY, SORT_MANUAL = "Tienda", "Actividad", "Manual"
ALL_PAGE = "Todas"
PAGE_SIZES = ["5", "10", "15", "20", "30", "35", ALL_PAGE]
_ORDER_FILE = config.DATA_DIR / "admin_order.json"
REMOTE_UPDATE_MIN = (1, 5, 0)  # primera versión cuyo agente entiende "Actualizar ahora"


def _version(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in text.split("."))
    except ValueError:
        return (0,)


def supports_remote_update(device: dict) -> bool:
    return bool(device.get("version")) and _version(device["version"]) >= REMOTE_UPDATE_MIN

_CONN = {
    "online": (theme.ONLINE, "Conectado"),
    "connecting": (theme.WARN, "Conectando…"),
    "offline": (theme.DANGER, "Sin conexión"),
    "error": (theme.DANGER, "Sesión inválida"),
}


def compute_layout(n: int, width: float, height: float) -> tuple[int, int]:
    """Columnas y ancho de tile que llenan el área con n pantallas (estilo videollamada).

    Si con tantas pantallas los tiles quedarían más chicos que MIN_TILE, se fija ese
    mínimo y el resto se ve con scroll.
    """
    if n == 0:
        return 1, MIN_TILE
    best_cols, best_w = 1, 0.0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        by_width = width / cols - GAP
        by_height = (height / rows - GAP - ScreenTile.CHROME_H) * 16 / 9 + ScreenTile.CHROME_W
        w = min(by_width, by_height)
        if w > best_w:
            best_cols, best_w = cols, w
    if best_w < MIN_TILE:
        best_cols = max(1, int(width // (MIN_TILE + GAP)))
        best_w = width / best_cols - GAP
    return best_cols, int(min(best_w, MAX_TILE))


DRAG_THRESHOLD = 8  # px antes de tratar el movimiento como arrastre y no como clic


class ScreenGrid(ctk.CTkScrollableFrame):
    def __init__(self, container, on_open, on_menu, on_layout, on_reorder):
        super().__init__(container, fg_color=theme.BG, corner_radius=0, scrollbar_button_color=theme.BORDER)
        self.container = container
        self.on_open, self.on_menu, self.on_layout, self.on_reorder = on_open, on_menu, on_layout, on_reorder
        self.inner = ctk.CTkFrame(self, fg_color="transparent")
        self.inner.pack(anchor="n")
        self.empty = ctk.CTkLabel(self, text="", font=theme.font(14), text_color=theme.MUTED)
        self.tiles: dict[int, ScreenTile] = {}
        self.order: list[int] = []
        self.cols = 1
        self._key = None
        self._job = None
        self._drag: dict | None = None
        container.bind("<Configure>", lambda _: self.schedule_layout(), add="+")

    # ---------- arrastrar para reordenar ----------

    def drag_press(self, device_id: int, event) -> None:
        self._drag = {"id": device_id, "x": event.x_root, "y": event.y_root, "moved": False}

    def drag_motion(self, device_id: int, event) -> None:
        drag = self._drag
        if not drag:
            return
        if not drag["moved"] and (abs(event.x_root - drag["x"]) > DRAG_THRESHOLD
                                  or abs(event.y_root - drag["y"]) > DRAG_THRESHOLD):
            drag["moved"] = True
            if tile := self.tiles.get(drag["id"]):
                tile.set_dragging(True)

    def drag_release(self, device_id: int, event) -> None:
        drag, self._drag = self._drag, None
        if not drag:
            return
        if not drag["moved"]:
            self.on_open(drag["id"])
            return
        if tile := self.tiles.get(drag["id"]):
            tile.set_dragging(False)
        target = self._tile_at(event.x_root, event.y_root)
        if target is not None and target != drag["id"]:
            self.on_reorder(drag["id"], target)

    def _tile_at(self, x_root: int, y_root: int) -> int | None:
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            for device_id, tile in self.tiles.items():
                if widget is tile:
                    return device_id
            widget = getattr(widget, "master", None)
        return None

    def sync(self, devices: list[dict], visible: list[dict], empty_text: str) -> None:
        ids = {d["id"] for d in devices}
        for device_id in [i for i in self.tiles if i not in ids]:
            self.tiles.pop(device_id).destroy()
        for device in devices:
            tile = self.tiles.get(device["id"])
            if tile:
                tile.update_device(device)
            else:
                self.tiles[device["id"]] = ScreenTile(self.inner, device, self)
        self.order = [d["id"] for d in visible]
        if self.order:
            self.empty.pack_forget()
        else:
            self.empty.configure(text=empty_text)
            self.empty.pack(pady=80)
        self._key = None
        self.schedule_layout()

    def schedule_layout(self) -> None:
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self._layout)

    def _layout(self) -> None:
        self._job = None
        scale = self._get_widget_scaling()
        width = self.container.winfo_width() / scale - 28  # scrollbar y márgenes
        height = self.container.winfo_height() / scale - 8
        if width < 100:
            return
        cols, tile_w = compute_layout(len(self.order), width, height)
        key = (tuple(self.order), cols, tile_w)
        if key == self._key:
            return
        self._key = key
        visible = set(self.order)
        for device_id, tile in self.tiles.items():
            if device_id not in visible:
                tile.grid_forget()
        for i, device_id in enumerate(self.order):
            tile = self.tiles[device_id]
            tile.grid(row=i // cols, column=i % cols, padx=GAP // 2, pady=GAP // 2)
            tile.resize(tile_w)
        if self.order:
            self.on_layout(self.order, self.tiles[self.order[0]].box()[0])


class AdminPage(ctk.CTkFrame):
    def __init__(self, master, bridge, token: str, user: dict, on_logout):
        super().__init__(master, fg_color=theme.BG)
        self.bridge, self.user, self.on_logout = bridge, user, on_logout
        self.api = Api(token)
        self.devices: list[dict] = []
        self.by_id: dict[int, dict] = {}
        self.live: LiveWindow | None = None
        self.watching: int | None = None  # PC en vivo: la de la ventana grande o la única tarjeta en pantalla
        self.active_at: dict[int, float] = {}  # time.monotonic() del último teclado/mouse por PC
        self.manual_order: list[int] = self._load_order()  # orden a voluntad del admin (arrastrando)
        self.page_size: int | None = None  # pantallas por página (None = todas)
        self.page_index = 0
        self._closed = False
        self._ticks = 0

        self._build_topbar()
        body = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        body.pack(fill="both", expand=True)

        self.screens = ctk.CTkFrame(body, fg_color=theme.BG, corner_radius=0)
        self._build_toolbar(self.screens)
        holder = ctk.CTkFrame(self.screens, fg_color=theme.BG, corner_radius=0)
        holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.grid_view = ScreenGrid(holder, self.open_live, self.tile_menu, self._on_layout, self._on_reorder)
        self.grid_view.pack(fill="both", expand=True)
        self.users_view = UsersPanel(body, bridge, self.api, user, self._auth_expired)
        self.screens.pack(fill="both", expand=True)

        self._toast: ctk.CTkFrame | None = None
        self.viewer = ViewerService(token, bridge.wrap(self._on_devices), bridge.wrap(self._on_activity),
                                    bridge.wrap(self._on_status), bridge.wrap(self._auth_expired),
                                    on_alert=bridge.wrap(self._on_alert))
        self.viewer.start()
        self.apply_filters()
        self._pump()
        self._tick_activity()

    # ---------- construcción ----------

    def _build_topbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=58)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="", image=ctk.CTkImage(draw_logo(64, None), size=(28, 28))).pack(
            side="left", padx=(18, 8))
        ctk.CTkLabel(bar, text=config.APP_NAME, font=theme.font(17, "bold"), text_color=theme.TEXT).pack(
            side="left")
        self.tabs = ctk.CTkSegmentedButton(bar, values=["Pantallas", "Usuarios"], command=self._switch_tab,
                                           font=theme.font(13, "bold"), height=34,
                                           selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
                                           unselected_color=theme.SURFACE_2, fg_color=theme.SURFACE_2)
        self.tabs.set("Pantallas")
        self.tabs.pack(side="left", padx=28)

        theme.button(bar, "ghost", text="Cerrar sesión", width=120, command=lambda: self.on_logout("")).pack(
            side="right", padx=(8, 18))
        ctk.CTkLabel(bar, text=self.user["display_name"] or self.user["username"], font=theme.font(13),
                     text_color=theme.TEXT).pack(side="right", padx=8)
        self.conn = ctk.CTkLabel(bar, text="", font=theme.font(12))
        self.conn.pack(side="right", padx=8)
        self._on_status("connecting", "")

    def _build_toolbar(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(12, 8))
        self.search = theme.entry(bar, width=260, height=34, placeholder_text="Buscar tienda o PC…")
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda _: self.apply_filters())
        self.store = ctk.CTkOptionMenu(bar, values=[ALL_STORES], width=220, height=34, font=theme.font(13),
                                       fg_color=theme.SURFACE_2, button_color=theme.SURFACE_2,
                                       button_hover_color=theme.BORDER, dropdown_fg_color=theme.SURFACE_2,
                                       dropdown_font=theme.font(13), command=lambda _: self.apply_filters())
        self.store.pack(side="left", padx=10)
        self.only_online = ctk.CTkSwitch(bar, text="Solo en línea", font=theme.font(13),
                                         progress_color=theme.ACCENT, command=self.apply_filters)
        self.only_online.select()
        self.only_online.pack(side="left", padx=6)
        ctk.CTkLabel(bar, text="Ordenar", font=theme.font(13), text_color=theme.MUTED).pack(side="left", padx=(18, 6))
        self.sort = ctk.CTkSegmentedButton(bar, values=[SORT_STORE, SORT_ACTIVITY, SORT_MANUAL], font=theme.font(12),
                                           height=30, command=lambda _: self._on_sort(),
                                           selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
                                           unselected_color=theme.SURFACE_2, fg_color=theme.SURFACE_2)
        self.sort.set(SORT_STORE)
        self.sort.pack(side="left")
        ctk.CTkLabel(bar, text="Por página", font=theme.font(13), text_color=theme.MUTED).pack(side="left", padx=(18, 6))
        self.page_menu = ctk.CTkOptionMenu(bar, values=PAGE_SIZES, width=90, height=30, font=theme.font(13),
                                           fg_color=theme.SURFACE_2, button_color=theme.SURFACE_2,
                                           button_hover_color=theme.BORDER, dropdown_fg_color=theme.SURFACE_2,
                                           dropdown_font=theme.font(13), command=lambda _: self._on_page_size())
        self.page_menu.set(ALL_PAGE)
        self.page_menu.pack(side="left")
        theme.button(bar, "ghost", text="Actualizar PCs", width=120, height=30, command=self.update_all).pack(
            side="left", padx=(18, 0))

        self.counter = ctk.CTkLabel(bar, text="", font=theme.font(13), text_color=theme.MUTED)
        self.counter.pack(side="right")
        self.pager = ctk.CTkFrame(bar, fg_color="transparent")
        theme.button(self.pager, "ghost", text="‹", width=30, height=30, command=lambda: self._turn_page(-1)).pack(
            side="left")
        self.page_label = ctk.CTkLabel(self.pager, text="", width=76, font=theme.font(12), text_color=theme.TEXT)
        self.page_label.pack(side="left")
        theme.button(self.pager, "ghost", text="›", width=30, height=30, command=lambda: self._turn_page(1)).pack(
            side="left")

    # ---------- datos ----------

    def _on_devices(self, devices: list[dict]) -> None:
        if self._closed:
            return
        self.devices = devices
        self.by_id = {d["id"]: d for d in devices}
        new = [d["id"] for d in devices if d["id"] not in self.manual_order]  # PCs nuevas al final del orden manual
        if new:
            self.manual_order.extend(new)
            self._save_order()
        now = time.monotonic()
        for d in devices:
            if d.get("idle") is not None:
                self.active_at[d["id"]] = now - d["idle"]
        stores = sorted({device_name(d) for d in devices}, key=str.lower)
        self.store.configure(values=[ALL_STORES, *stores])
        if self.store.get() not in stores:
            self.store.set(ALL_STORES)
        self.apply_filters()
        if self.live:
            device = self.by_id.get(self.live.device_id)
            if not device or not device["online"]:
                self.live.set_offline()

    def apply_filters(self) -> None:
        query = self.search.get().strip().lower()
        store = self.store.get()
        only_online = bool(self.only_online.get())
        visible = [
            d for d in self.devices
            if (not only_online or d["online"])
            and (store == ALL_STORES or device_name(d) == store)
            and (not query or query in f"{device_name(d)} {d['hostname']} {d['username']}".lower())
        ]
        sort = self.sort.get()
        if sort == SORT_MANUAL:
            visible.sort(key=lambda d: self._manual_rank(d["id"]))
        elif sort == SORT_ACTIVITY:
            now = time.monotonic()
            visible.sort(key=lambda d: (not d["online"], now - self.active_at.get(d["id"], -1e9)))
        else:
            visible.sort(key=lambda d: (not d["online"], device_name(d).lower(), d["hostname"].lower()))

        page = self._paginate(visible)
        online = sum(d["online"] for d in self.devices)
        self.counter.configure(text=f"{online} en línea  ·  {len(self.devices)} PCs")
        if not self.devices:
            empty = "Aún no hay PCs registradas.\nInicia sesión con una cuenta de tienda en cada PC."
        elif only_online and not online:
            empty = "No hay pantallas en línea en este momento."
        else:
            empty = "Sin resultados para este filtro."
        self.grid_view.sync(self.devices, page, empty)
        for device_id, tile in self.grid_view.tiles.items():
            tile.active_at = self.active_at.get(device_id)
            tile.refresh_activity()
        self._sync_watch()

    # ---------- páginas y orden manual ----------

    def _paginate(self, visible: list[dict]) -> list[dict]:
        size = self.page_size
        if not size or len(visible) <= size:
            self.page_index = 0
            self.pager.pack_forget()
            return visible
        pages = (len(visible) + size - 1) // size
        self.page_index = max(0, min(self.page_index, pages - 1))
        self.page_label.configure(text=f"Página {self.page_index + 1}/{pages}")
        self.pager.pack(side="right", padx=16)
        start = self.page_index * size
        return visible[start:start + size]

    def _on_page_size(self) -> None:
        value = self.page_menu.get()
        self.page_size = None if value == ALL_PAGE else int(value)
        self.page_index = 0
        self.apply_filters()

    def _turn_page(self, step: int) -> None:
        self.page_index += step
        self.apply_filters()

    def _on_sort(self) -> None:
        self.page_index = 0
        self.apply_filters()

    def _manual_rank(self, device_id: int) -> int:
        try:
            return self.manual_order.index(device_id)
        except ValueError:
            return len(self.manual_order)

    def _on_reorder(self, dragged: int, target: int) -> None:
        order = [i for i in self.manual_order if i != dragged]
        try:
            order.insert(order.index(target), dragged)
        except ValueError:
            order.append(dragged)
        self.manual_order = order
        self._save_order()
        if self.sort.get() != SORT_MANUAL:
            self.sort.set(SORT_MANUAL)  # arrastrar activa el orden a voluntad
        self.apply_filters()

    def _load_order(self) -> list[int]:
        try:
            data = json.loads(_ORDER_FILE.read_text(encoding="utf-8"))
            return [int(i) for i in data if isinstance(i, int)]
        except (OSError, ValueError):
            return []

    def _save_order(self) -> None:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _ORDER_FILE.write_text(json.dumps(self.manual_order), encoding="utf-8")
        except OSError:
            pass

    def _on_layout(self, order: list[int], thumb_width: int) -> None:
        self.viewer.set_view(thumb_width, order)

    def _focus_id(self) -> int | None:
        """Con una sola PC en pantalla su tarjeta muestra el en vivo, igual que la ventana grande."""
        order = self.grid_view.order
        if self.live or self.tabs.get() != "Pantallas" or len(order) != 1:
            return None
        device = self.by_id.get(order[0])
        return order[0] if device and device["online"] else None

    def _sync_watch(self) -> None:
        focus = self._focus_id()
        for device_id, tile in self.grid_view.tiles.items():
            tile.set_live(device_id == focus)
        target = self.live.device_id if self.live else focus
        if target != self.watching:
            self.watching = target
            self.viewer.watch(target)

    def _on_activity(self, device_id: int, idle: float | None) -> None:
        if self._closed or idle is None:
            return
        self.active_at[device_id] = time.monotonic() - idle
        if tile := self.grid_view.tiles.get(device_id):
            tile.active_at = self.active_at[device_id]
            tile.refresh_activity()

    def _tick_activity(self) -> None:
        """Refresca los "hace N min" y, si se ordena por actividad, reacomoda cada 10 s."""
        if self._closed:
            return
        self._ticks += 1
        if self.sort.get() == SORT_ACTIVITY and self._ticks % 5 == 0:
            self.apply_filters()
        else:
            for tile in self.grid_view.tiles.values():
                tile.refresh_activity()
        self.after(2000, self._tick_activity)

    def _pump(self) -> None:
        if self._closed:
            return
        try:
            tiles = self.grid_view.tiles
            if self.live:
                self.viewer.display_box = self.live.box()
            elif self.watching in tiles:
                self.viewer.display_box = tiles[self.watching].box()
            for (kind, device_id), image in self.viewer.take_frames().items():
                tile = tiles.get(device_id)
                if tile and kind == KIND_THUMB and not tile.live:
                    tile.set_image(image)
                elif tile and kind == KIND_LIVE and tile.live:
                    tile.set_frame(image)
                if self.live and self.live.device_id == device_id:
                    if kind == KIND_LIVE:
                        self.live.set_frame(image, live=True)
                    elif not self.live.got_live:
                        self.live.set_frame(image, live=False)
        finally:
            self.after(30, self._pump)

    def _on_status(self, state: str, _text: str) -> None:
        color, label = _CONN.get(state, (theme.MUTED, state))
        self.conn.configure(text=f"● {label}", text_color=color)

    def _auth_expired(self) -> None:
        if not self._closed:
            self.on_logout("Tu sesión expiró. Vuelve a ingresar.")

    def _on_alert(self, msg: dict) -> None:
        if self._closed:
            return
        device = self.by_id.get(msg.get("device_id"))
        name = device_name(device) if device else msg.get("hostname", "una PC")
        when = ""
        if msg.get("at"):
            when = " a las " + datetime.fromtimestamp(msg["at"]).strftime("%H:%M")
        self._show_toast(f"⚠  {name} ({msg.get('hostname', '')}) fue cerrada manualmente{when} y se reinició sola")

    def _show_toast(self, text: str, color: str = theme.DANGER) -> None:
        if self._toast is not None:
            self._toast.destroy()
        toast = ctk.CTkFrame(self, fg_color=color, corner_radius=8)
        ctk.CTkLabel(toast, text=text, font=theme.font(13, "bold"), text_color="#ffffff").pack(padx=16, pady=10)
        toast.place(relx=0.5, y=70, anchor="n")
        toast.lift()
        self._toast = toast
        self.after(12000, lambda: toast.destroy() if toast.winfo_exists() else None)

    # ---------- acciones ----------

    def _switch_tab(self, value: str) -> None:
        if value == "Usuarios":
            self.screens.pack_forget()
            self.users_view.pack(fill="both", expand=True)
            self.users_view.refresh()
        else:
            self.users_view.pack_forget()
            self.screens.pack(fill="both", expand=True)
        self._sync_watch()

    def open_live(self, device_id: int) -> None:
        device = self.by_id.get(device_id)
        if not device or not device["online"]:
            return
        if self.live:
            previous, self.live = self.live, None
            previous.destroy()
        self.live = LiveWindow(self, device, on_close=self._live_closed)
        tile = self.grid_view.tiles.get(device_id)
        if tile and tile.image is not None:
            self.live.set_frame(tile.image, live=False)
        self._sync_watch()

    def _live_closed(self) -> None:
        self.live = None
        self._sync_watch()

    def tile_menu(self, event, device: dict) -> None:
        menu = tk.Menu(self, tearoff=0, bg=theme.SURFACE_2, fg=theme.TEXT, activebackground=theme.ACCENT,
                       activeforeground="#ffffff", disabledforeground=theme.OFFLINE, bd=0)
        menu.add_command(label="Ver en vivo", command=lambda: self.open_live(device["id"]),
                         state="normal" if device["online"] else "disabled")
        can_update = device["online"] and supports_remote_update(device)
        menu.add_command(label="Actualizar ahora" if can_update or not device["online"]
                         else f"Actualizar ahora (requiere v{'.'.join(map(str, REMOTE_UPDATE_MIN))}+)",
                         command=lambda: self.update_devices([device]), state="normal" if can_update else "disabled")
        menu.add_separator()
        menu.add_command(label="Quitar PC del listado", command=lambda: self.delete_device(device),
                         state="disabled" if device["online"] else "normal")
        menu.tk_popup(event.x_root, event.y_root)

    def update_all(self) -> None:
        targets = [d for d in self.devices if d["online"] and supports_remote_update(d)]
        old = sum(1 for d in self.devices if d["online"] and not supports_remote_update(d))
        if not targets:
            self._show_toast("Ninguna PC en línea tiene la versión que acepta actualizar a distancia"
                             + (f" ({old} con versión vieja: se actualizan solas)" if old else ""), theme.WARN)
            return
        ConfirmDialog(self, "Actualizar PCs",
                      f"Se pedirá a {len(targets)} PC(s) en línea que busquen e instalen la última versión. "
                      "La app se cierra unos segundos y vuelve sola."
                      + (f"\n\n{old} PC(s) con versión vieja no lo aceptan: se actualizan solas." if old else ""),
                      "Actualizar", lambda: self.update_devices(targets))

    def update_devices(self, devices: list[dict]) -> None:
        self.viewer.request_update([d["id"] for d in devices])
        names = device_name(devices[0]) if len(devices) == 1 else f"{len(devices)} PCs"
        self._show_toast(f"Actualización pedida a {names}: se aplica en ~1 minuto si hay versión nueva",
                         theme.ACCENT)

    def delete_device(self, device: dict) -> None:
        def go():
            self.bridge.run_bg(lambda: self.api.delete_device(device["id"]), None, self._api_error)

        ConfirmDialog(self, "Quitar PC",
                      f"Se quitará {device['hostname']} ({device_name(device)}) del listado. "
                      "Si vuelve a conectarse aparecerá de nuevo.", "Quitar", go)

    def _api_error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError) and exc.status == 401:
            self._auth_expired()

    def shutdown(self) -> None:
        self._closed = True
        # CustomTkinter no da de baja del ajuste de DPI el desplegable de un CTkOptionMenu al destruirlo:
        # sin esto, después de cerrar sesión, llama a un menú que ya no existe (TclError en el log)
        for menu in (self.store, self.page_menu):
            dropdown = getattr(menu, "_dropdown_menu", None)
            if dropdown is not None:
                ScalingTracker.remove_widget(dropdown._set_scaling, dropdown)
        self.viewer.stop()
        if self.live:
            self.live.destroy()
            self.live = None
