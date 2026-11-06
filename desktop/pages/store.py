import customtkinter as ctk

from shared import config, theme
from shared.logo import draw_logo

_DOT = {
    "online": (theme.ONLINE, "Conectado"),
    "live": (theme.LIVE, "Conectado"),
    "connecting": (theme.WARN, "Conectando"),
    "offline": (theme.OFFLINE, "Sin conexión"),
    "error": (theme.DANGER, "Sesión inválida"),
}


class StorePage(ctk.CTkFrame):
    """Ventana chica de estado del modo tienda. Normalmente vive oculta en la bandeja."""

    def __init__(self, master, user: dict, on_hide):
        super().__init__(master, fg_color=theme.BG)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 10))
        ctk.CTkLabel(head, text="", image=ctk.CTkImage(draw_logo(64, None), size=(26, 26))).pack(side="left")
        ctk.CTkLabel(head, text=config.APP_NAME, font=theme.font(16, "bold"),
                     text_color=theme.TEXT).pack(side="left", padx=(8, 0))

        card = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=12, border_width=1,
                            border_color=theme.BORDER)
        card.pack(fill="x", padx=22)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 2))
        self.dot = ctk.CTkLabel(row, text="●", font=theme.font(16))
        self.dot.pack(side="left")
        self.state = ctk.CTkLabel(row, text="", font=theme.font(15, "bold"), text_color=theme.TEXT)
        self.state.pack(side="left", padx=(6, 0))
        self.detail = ctk.CTkLabel(card, text="", font=theme.font(12), text_color=theme.MUTED, anchor="w")
        self.detail.pack(fill="x", padx=16, pady=(0, 12))

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(fill="x", padx=24, pady=(12, 0))
        for label, value in (("Tienda", user["display_name"] or user["username"]), ("PC", config.HOSTNAME)):
            line = ctk.CTkFrame(info, fg_color="transparent")
            line.pack(fill="x")
            ctk.CTkLabel(line, text=label, width=60, anchor="w", font=theme.font(12),
                         text_color=theme.MUTED).pack(side="left")
            ctk.CTkLabel(line, text=value, anchor="w", font=theme.font(12, "bold"),
                         text_color=theme.TEXT).pack(side="left")

        ctk.CTkLabel(self, text="PC conectada a la red.",
                     font=theme.font(11), text_color=theme.MUTED, wraplength=360,
                     justify="left").pack(fill="x", padx=24, pady=(12, 0))
        theme.button(self, "ghost", text="Cerrar Programa", command=on_hide).pack(
            fill="x", padx=22, pady=(14, 18))
        self.set_status("connecting", "Conectando…")

    def set_status(self, state: str, text: str) -> None:
        color, title = _DOT.get(state, (theme.OFFLINE, state))
        self.dot.configure(text_color=color)
        self.state.configure(text=title)
        self.detail.configure(text=text)
