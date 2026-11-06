from __future__ import annotations

import customtkinter as ctk

from services.api import Api, ApiError
from shared import theme


def error_text(exc: Exception) -> str:
    return exc.message if isinstance(exc, ApiError) else "Error inesperado"


class Dialog(ctk.CTkToplevel):
    """Base modal centrada en pantalla."""

    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color=theme.BG)
        self.title(title)
        self.resizable(False, False)
        if master.winfo_toplevel().winfo_viewable():
            self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _: self.close())

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=26, pady=22)
        ctk.CTkLabel(self.body, text=title, font=theme.font(17, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x")
        if subtitle:
            ctk.CTkLabel(self.body, text=subtitle, font=theme.font(12), text_color=theme.MUTED, anchor="w",
                         justify="left", wraplength=320).pack(fill="x", pady=(2, 0))
        self.form = ctk.CTkFrame(self.body, fg_color="transparent")
        self.form.pack(fill="x", pady=(16, 0))
        self.error = ctk.CTkLabel(self.body, text="", font=theme.font(12), text_color=theme.DANGER,
                                  anchor="w", justify="left", wraplength=320)
        self.error.pack(fill="x", pady=(8, 0))
        self.actions = ctk.CTkFrame(self.body, fg_color="transparent")
        self.actions.pack(fill="x", pady=(10, 0))
        # CTkToplevel aplica estilos tras mostrarse: el grab y el centrado van después
        self.after(120, self._show)

    def _show(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{x}+{y}")
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        try:
            self.grab_set()
        except Exception:
            pass

    def field(self, label: str, **entry_kw) -> ctk.CTkEntry:
        ctk.CTkLabel(self.form, text=label, font=theme.font(12), text_color=theme.MUTED,
                     anchor="w").pack(fill="x", pady=(8, 2))
        entry = theme.entry(self.form, width=320, **entry_kw)
        entry.pack(fill="x")
        return entry

    def add_actions(self, ok_text: str, on_ok, kind: str = "primary") -> ctk.CTkButton:
        ok = theme.button(self.actions, kind, text=ok_text, width=130, command=on_ok)
        ok.pack(side="right")
        theme.button(self.actions, "ghost", text="Cancelar", width=100, command=self.close).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _: on_ok())
        return ok

    def close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class AdminUnlockDialog(Dialog):
    """Pide credenciales de un admin para acciones protegidas en la PC de tienda."""

    def __init__(self, master, bridge, reason: str, on_success):
        super().__init__(master, "Autorización de administrador", reason)
        self.bridge = bridge
        self.on_success = on_success
        self.user = self.field("Usuario administrador")
        self.password = self.field("Contraseña", show="•")
        self.ok = self.add_actions("Autorizar", self.submit)
        self.after(200, self.user.focus_set)

    def submit(self) -> None:
        username, password = self.user.get().strip(), self.password.get()
        if not username or not password:
            self.error.configure(text="Completa usuario y contraseña")
            return
        self.ok.configure(state="disabled", text="Verificando…")
        self.bridge.run_bg(lambda: Api().login(username, password), self._ok, self._fail)

    def _ok(self, result: dict) -> None:
        if result["user"]["role"] != "admin":
            self._fail(ApiError(403, "Ese usuario no es administrador"))
            return
        self.close()
        self.on_success()

    def _fail(self, exc: Exception) -> None:
        if not self.winfo_exists():
            return
        self.ok.configure(state="normal", text="Autorizar")
        self.error.configure(text=error_text(exc))


class ConfirmDialog(Dialog):
    def __init__(self, master, title: str, message: str, ok_text: str, on_yes):
        super().__init__(master, title, message)
        self.on_yes = on_yes
        self.add_actions(ok_text, self._yes, "danger")

    def _yes(self) -> None:
        self.close()
        self.on_yes()


class UserDialog(Dialog):
    ROLES = {"Tienda (transmite)": "tienda", "Administrador (ve todo)": "admin"}

    def __init__(self, master, bridge, api: Api, on_saved, user: dict | None = None):
        editing = user is not None
        super().__init__(master, "Editar usuario" if editing else "Nuevo usuario",
                         "Las cuentas de tienda solo transmiten su pantalla." if not editing else "")
        self.bridge, self.api, self.on_saved, self.user_data = bridge, api, on_saved, user

        self.username = self.field("Usuario (para iniciar sesión)")
        self.display = self.field("Nombre visible (ej. Tienda Centro — Caja 1)")
        ctk.CTkLabel(self.form, text="Rol", font=theme.font(12), text_color=theme.MUTED,
                     anchor="w").pack(fill="x", pady=(8, 2))
        self.role = ctk.CTkSegmentedButton(self.form, values=list(self.ROLES), font=theme.font(12),
                                           selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
                                           unselected_color=theme.SURFACE_2, fg_color=theme.SURFACE_2)
        self.role.pack(fill="x")
        self.password = self.field("Contraseña" + (" (vacío = no cambiar)" if editing else ""), show="•")
        self.active = ctk.CTkSwitch(self.form, text="Usuario activo", font=theme.font(12), progress_color=theme.ACCENT)

        if editing:
            self.username.insert(0, user["username"])
            self.username.configure(state="disabled", text_color=theme.MUTED)
            self.display.insert(0, user["display_name"])
            self.role.set(next(k for k, v in self.ROLES.items() if v == user["role"]))
            self.active.pack(anchor="w", pady=(12, 0))
            if user["active"]:
                self.active.select()
        else:
            self.role.set(next(iter(self.ROLES)))
        self.ok = self.add_actions("Guardar", self.submit)
        self.after(200, (self.display if editing else self.username).focus_set)

    def submit(self) -> None:
        role = self.ROLES[self.role.get()]
        display = self.display.get().strip()
        password = self.password.get()
        if self.user_data:
            fields = {"display_name": display, "role": role, "active": bool(self.active.get())}
            if password:
                fields["password"] = password
            uid = self.user_data["id"]
            job = lambda: self.api.update_user(uid, **fields)
        else:
            fields = {"username": self.username.get().strip(), "password": password,
                      "role": role, "display_name": display}
            job = lambda: self.api.create_user(**fields)
        self.ok.configure(state="disabled", text="Guardando…")
        self.bridge.run_bg(job, self._ok, self._fail)

    def _ok(self, _result) -> None:
        self.close()
        self.on_saved()

    def _fail(self, exc: Exception) -> None:
        if not self.winfo_exists():
            return
        self.ok.configure(state="normal", text="Guardar")
        self.error.configure(text=error_text(exc))
