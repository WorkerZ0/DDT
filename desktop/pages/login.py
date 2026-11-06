import customtkinter as ctk

from components.dialogs import error_text
from services.api import Api
from shared import config, theme
from shared.logo import draw_logo


class LoginPage(ctk.CTkFrame):
    def __init__(self, master, bridge, on_login, message: str = ""):
        super().__init__(master, fg_color=theme.BG)
        self.bridge = bridge
        self.on_login = on_login

        card = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=14, border_width=1,
                            border_color=theme.BORDER)
        card.place(relx=0.5, rely=0.47, anchor="center")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=34, pady=30)

        logo = ctk.CTkImage(draw_logo(128, None), size=(52, 52))
        ctk.CTkLabel(inner, text="", image=logo).pack()
        ctk.CTkLabel(inner, text=config.APP_NAME, font=theme.font(22, "bold"),
                     text_color=theme.TEXT).pack(pady=(8, 0))
        ctk.CTkLabel(inner, text="Inicia sesión para continuar", font=theme.font(13),
                     text_color=theme.MUTED).pack(pady=(0, 18))

        self.user = theme.entry(inner, width=300, placeholder_text="Usuario")
        self.user.pack(pady=(0, 10))
        self.password = theme.entry(inner, width=300, placeholder_text="Contraseña", show="•")
        self.password.pack()
        self.error = ctk.CTkLabel(inner, text=message, font=theme.font(12), text_color=theme.DANGER,
                                  wraplength=300)
        self.error.pack(pady=(8, 4))
        self.submit_btn = theme.button(inner, text="Ingresar", width=300, height=40, command=self.submit)
        self.submit_btn.pack()

        host = config.SERVER.split("://", 1)[-1]
        ctk.CTkLabel(self, text=f"Servidor {host}  ·  PC {config.HOSTNAME}", font=theme.font(11),
                     text_color=theme.MUTED).place(relx=0.5, rely=0.96, anchor="s")

        for entry in (self.user, self.password):
            entry.bind("<Return>", lambda _: self.submit())
        self.after(150, self.user.focus_set)

    def submit(self) -> None:
        username, password = self.user.get().strip(), self.password.get()
        if not username or not password:
            self.error.configure(text="Completa usuario y contraseña")
            return
        self.error.configure(text="")
        self.submit_btn.configure(state="disabled", text="Ingresando…")
        self.bridge.run_bg(lambda: Api().login(username, password), self._ok, self._fail)

    def _ok(self, result: dict) -> None:
        self.on_login(result["token"], result["user"])

    def _fail(self, exc: Exception) -> None:
        if not self.winfo_exists():
            return
        self.submit_btn.configure(state="normal", text="Ingresar")
        self.error.configure(text=error_text(exc))
        self.password.delete(0, "end")
