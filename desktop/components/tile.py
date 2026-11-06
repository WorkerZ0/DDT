from __future__ import annotations

import time
import warnings
from datetime import datetime, timezone

import customtkinter as ctk
from PIL import Image, ImageTk

from shared import theme

_BLANK = Image.new("RGB", (1, 1), theme.BG)
# En vivo la tarjeta dibuja con un PhotoImage en píxeles reales (ya escalado): CTk avisa que no es CTkImage
warnings.filterwarnings("ignore", message="CTkLabel Warning: Given image is not CTkImage")


def fit(img_size: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    iw, ih = img_size
    bw, bh = box
    scale = min(bw / iw, bh / ih)
    return max(1, int(iw * scale)), max(1, int(ih * scale))


def format_seen(utc_text: str | None) -> str:
    if not utc_text:
        return "nunca conectada"
    try:
        dt = datetime.strptime(utc_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        return utc_text
    return "visto " + dt.strftime("%d/%m %H:%M")


def ellipsize(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max(1, max_chars - 1)] + "…"


def device_name(device: dict) -> str:
    return device["display_name"] or device["username"]


def activity_text(idle: float | None) -> tuple[str, str]:
    """Texto y color del último uso de teclado/mouse."""
    if idle is None:
        return "", theme.MUTED
    if idle < 15:
        return "● activo ahora", theme.ONLINE
    if idle < 60:
        return f"activo hace {int(idle)} s", theme.ONLINE
    minutes = int(idle // 60)
    if minutes < 60:
        return f"inactivo {minutes} min", theme.WARN if minutes >= 5 else theme.MUTED
    return f"inactivo {minutes // 60} h {minutes % 60:02d} min", theme.WARN


class ScreenTile(ctk.CTkFrame):
    PAD = 6
    CHROME_W = 2 * PAD + 2  # ancho extra del tile sobre la imagen
    CHROME_H = 62           # alto del pie (nombre + host) y márgenes

    def __init__(self, master, device: dict, grid):
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=10, border_width=1,
                         border_color=theme.BORDER)
        self.device = device
        self.image: Image.Image | None = None
        self.live = False  # única PC en pantalla: muestra el en vivo en vez de la miniatura
        self._photo: ImageTk.PhotoImage | None = None
        self._size = (320, 180)

        self.screen = ctk.CTkLabel(self, text="", width=320, height=180, fg_color=theme.BG, corner_radius=6,
                                   text_color=theme.MUTED, font=theme.font(12), compound="center")
        self.screen.pack(padx=self.PAD, pady=(self.PAD, 4))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=10)
        self.dot = ctk.CTkLabel(row, text="●", width=14, font=theme.font(12))
        self.dot.pack(side="left")
        self.name = ctk.CTkLabel(row, text="", anchor="w", font=theme.font(13, "bold"), text_color=theme.TEXT)
        self.name.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.badge = ctk.CTkLabel(row, text="EN VIVO", width=56, height=18, corner_radius=4, fg_color=theme.LIVE,
                                  text_color="#ffffff", font=theme.font(10, "bold"))
        sub_row = ctk.CTkFrame(self, fg_color="transparent")
        sub_row.pack(fill="x", padx=12, pady=(0, 8))
        self.activity = ctk.CTkLabel(sub_row, text="", height=16, font=theme.font(11, "bold"))
        self.activity.pack(side="right")
        self.sub = ctk.CTkLabel(sub_row, text="", anchor="w", height=16, font=theme.font(11), text_color=theme.MUTED)
        self.sub.pack(side="left", fill="x", expand=True)
        self.active_at: float | None = None  # time.monotonic() del último teclado/mouse

        # Press/motion/release van al grid: él decide si fue clic (abrir) o arrastre (reordenar)
        for widget in (self, self.screen, self.dot, self.name, self.sub, self.activity):
            widget.bind("<ButtonPress-1>", lambda e: grid.drag_press(self.device["id"], e))
            widget.bind("<B1-Motion>", lambda e: grid.drag_motion(self.device["id"], e))
            widget.bind("<ButtonRelease-1>", lambda e: grid.drag_release(self.device["id"], e))
            widget.bind("<Button-3>", lambda e: grid.on_menu(e, self.device))
            widget.configure(cursor="hand2")
        self.update_device(device)

    def set_dragging(self, on: bool) -> None:
        self.configure(border_color=theme.ACCENT if on else theme.BORDER, border_width=2 if on else 1)

    @property
    def online(self) -> bool:
        return self.device["online"]

    def update_device(self, device: dict) -> None:
        self.device = device
        self.dot.configure(text_color=theme.ONLINE if device["online"] else theme.OFFLINE)
        state = "en línea" if device["online"] else format_seen(device["last_seen"])
        chars = max(8, self._size[0] // 8)
        self.name.configure(text=ellipsize(device_name(device), chars - 8))
        sub = device["hostname"] if device["online"] else f"{device['hostname']} · {state}"
        if device["online"] and device.get("version"):
            sub += f" · v{device['version']}"
        self.sub.configure(text=ellipsize(sub, chars - 16))
        if device["watchers"] > 0:
            self.badge.pack(side="right")
        else:
            self.badge.pack_forget()
        self.refresh_activity()
        self._render()

    def refresh_activity(self) -> None:
        text, color = activity_text(self.idle()) if self.online else ("", theme.MUTED)
        self.activity.configure(text=text, text_color=color)

    def idle(self) -> float | None:
        return None if self.active_at is None else time.monotonic() - self.active_at

    def set_image(self, image: Image.Image) -> None:
        self.image = image
        self._render()

    def box(self) -> tuple[int, int]:
        """Píxeles reales disponibles para la imagen."""
        scale = self._get_widget_scaling()
        return round(self._size[0] * scale), round(self._size[1] * scale)

    def set_live(self, live: bool) -> None:
        if live != self.live:
            self.live = live
            self._photo = None
            self._render()

    def set_frame(self, image: Image.Image) -> None:
        """Frame en vivo: se pega sobre el mismo PhotoImage (crear imágenes nuevas a 25 fps se nota)."""
        self.image = image
        size = fit(image.size, self.box())
        if image.size != size:
            image = image.resize(size, Image.BILINEAR)
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self._photo is not None and (self._photo.width(), self._photo.height()) == size:
            self._photo.paste(image)
        else:
            self._photo = ImageTk.PhotoImage(image)
            self.screen.configure(image=self._photo, text="")

    def resize(self, tile_width: int) -> None:
        w = max(120, tile_width - self.CHROME_W)
        self._size = (w, round(w * 9 / 16))
        self.screen.configure(width=self._size[0], height=self._size[1])
        self.update_device(self.device)

    def _render(self) -> None:
        if self.live and self.image is not None and self.online:
            self.set_frame(self.image)
        elif self.online and self.image is not None:
            img = ctk.CTkImage(self.image, size=fit(self.image.size, self._size))
            self.screen.configure(image=img, text="")
        else:
            img = ctk.CTkImage(_BLANK, size=self._size)
            self.screen.configure(image=img, text="Esperando imagen…" if self.online else "Sin conexión")
