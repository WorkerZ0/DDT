from __future__ import annotations

import time
import tkinter as tk
from collections import deque

import customtkinter as ctk
from PIL import Image, ImageTk

from components.tile import device_name, fit
from services.viewer import CAN_DECODE_VIDEO
from shared import theme


class LiveWindow(ctk.CTkToplevel):
    """Vista grande de una PC. Mientras está abierta el servidor pide frames en vivo.

    Dibuja con un PhotoImage reutilizado (paste) en vez de CTkImage: a 25 fps crear
    imágenes nuevas por frame se nota.
    """

    def __init__(self, master, device: dict, on_close):
        super().__init__(master, fg_color="#000000")
        self.device_id = device["id"]
        self.video = device.get("video", False)
        self.on_close = on_close
        self.got_live = False
        self._image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._times: deque[float] = deque(maxlen=60)
        self.title(f"En vivo — {device_name(device)} ({device['hostname']})")
        scale = self._get_window_scaling()
        sw, sh = self.winfo_screenwidth() / scale, self.winfo_screenheight() / scale
        w, h = int(min(1180, sw * 0.85)), int(min(740, sh * 0.8))
        self.geometry(f"{w}x{h}+{int((sw - w) / 2 * scale)}+{int((sh - h) / 3 * scale)}")
        self.minsize(480, 320)

        self.stage = tk.Frame(self, bg="#000000", highlightthickness=0)
        self.stage.pack(fill="both", expand=True)
        self.screen = tk.Label(self.stage, bg="#000000", fg=theme.MUTED, text="Conectando…",
                               font=(theme.FAMILY, 12), bd=0)
        self.screen.place(relx=0.5, rely=0.5, anchor="center")

        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=40)
        bar.pack(fill="x")
        self.status = ctk.CTkLabel(bar, text="", font=theme.font(12, "bold"), text_color=theme.WARN)
        self.status.pack(side="left", padx=14, pady=8)
        ctk.CTkLabel(bar, text=f"{device_name(device)}  ·  {device['hostname']}", font=theme.font(12),
                     text_color=theme.MUTED).pack(side="left")
        theme.button(bar, "ghost", text="Pantalla completa (F11)", height=28,
                     command=self.toggle_fullscreen).pack(side="right", padx=10)
        self.rate = ctk.CTkLabel(bar, text="", font=theme.font(12), text_color=theme.MUTED)
        self.rate.pack(side="right", padx=10)
        if self.video and not CAN_DECODE_VIDEO:
            self.set_status("Esta PC no puede mostrar video en vivo (requiere Windows 8.1 o superior, 64 bits)",
                            theme.WARN)
        else:
            self.set_status("Esperando imagen en vivo…", theme.WARN)

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<F11>", lambda _: self.toggle_fullscreen())
        self.bind("<Escape>", lambda _: self.attributes("-fullscreen", False))
        self.stage.bind("<Configure>", lambda _: self._render())
        self.after(150, self._raise)
        self.after(1000, self._update_rate)

    def _raise(self) -> None:
        self.lift()
        self.focus_force()

    def toggle_fullscreen(self) -> None:
        self.attributes("-fullscreen", not self.attributes("-fullscreen"))

    def box(self) -> tuple[int, int]:
        """Píxeles disponibles para la imagen."""
        return max(2, self.stage.winfo_width()), max(2, self.stage.winfo_height())

    def set_status(self, text: str, color: str) -> None:
        self.status.configure(text=f"● {text}", text_color=color)

    def set_frame(self, image: Image.Image, live: bool) -> None:
        if live:
            self._times.append(time.monotonic())
            if not self.got_live:
                self.got_live = True
                self.set_status("EN VIVO", theme.LIVE)
        self._image = image
        self._render()

    def set_offline(self) -> None:
        self.set_status("PC desconectada", theme.OFFLINE)

    def _update_rate(self) -> None:
        if not self.winfo_exists():
            return
        now = time.monotonic()
        fps = sum(1 for t in self._times if now - t <= 1.0)
        mode = "Video H.264" if self.video else "JPEG"
        self.rate.configure(text=f"{mode} · {fps} fps" if self.got_live else mode)
        self.after(1000, self._update_rate)

    def _render(self) -> None:
        if self._image is None:
            return
        box = self.box()
        if box[0] < 10 or box[1] < 10:
            return
        size = fit(self._image.size, box)
        image = self._image if self._image.size == size else self._image.resize(size, Image.BILINEAR)
        if image.mode != "RGB":
            image = image.convert("RGB")
        if self._photo is not None and (self._photo.width(), self._photo.height()) == size:
            self._photo.paste(image)
        else:
            self._photo = ImageTk.PhotoImage(image)
            self.screen.configure(image=self._photo, text="")

    def close(self) -> None:
        self.on_close()
        self.destroy()
