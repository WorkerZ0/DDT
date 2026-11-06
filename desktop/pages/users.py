from __future__ import annotations

import customtkinter as ctk

from components.dialogs import ConfirmDialog, UserDialog, error_text
from services.api import Api, ApiError
from shared import theme

_COLUMNS = (("Usuario", 170), ("Nombre visible", 280), ("Rol", 110), ("Estado", 100), ("", 190))


class UsersPanel(ctk.CTkFrame):
    def __init__(self, master, bridge, api: Api, current_user: dict, on_auth_error):
        super().__init__(master, fg_color=theme.BG)
        self.bridge, self.api, self.me, self.on_auth_error = bridge, api, current_user, on_auth_error

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 12))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Usuarios", font=theme.font(20, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(titles, text="Las cuentas de tienda transmiten su pantalla; las de administrador ven y gestionan.",
                     font=theme.font(12), text_color=theme.MUTED, anchor="w").pack(fill="x")
        theme.button(head, text="+ Nuevo usuario", command=self.new_user).pack(side="right")

        table = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=12, border_width=1,
                             border_color=theme.BORDER)
        table.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        header = ctk.CTkFrame(table, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))
        self._grid_columns(header)
        for col, (title, _) in enumerate(_COLUMNS):
            ctk.CTkLabel(header, text=title.upper(), font=theme.font(11, "bold"), text_color=theme.MUTED,
                         anchor="w").grid(row=0, column=col, sticky="w", padx=6)
        self.rows = ctk.CTkScrollableFrame(table, fg_color="transparent", scrollbar_button_color=theme.BORDER)
        self.rows.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.status = ctk.CTkLabel(self.rows, text="Cargando…", font=theme.font(12), text_color=theme.MUTED)
        self.status.pack(pady=20)

    @staticmethod
    def _grid_columns(frame) -> None:
        for col, (_, width) in enumerate(_COLUMNS):
            frame.grid_columnconfigure(col, minsize=width, weight=1 if col == 1 else 0)

    def refresh(self) -> None:
        self.bridge.run_bg(self.api.users, self._render, self._error)

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError) and exc.status == 401:
            self.on_auth_error()
            return
        if self.winfo_exists():
            self.status.configure(text=error_text(exc))

    def _render(self, users: list[dict]) -> None:
        for child in self.rows.winfo_children():
            child.destroy()
        for i, user in enumerate(users):
            row = ctk.CTkFrame(self.rows, fg_color=theme.SURFACE_2 if i % 2 == 0 else "transparent",
                               corner_radius=8)
            row.pack(fill="x", pady=1)
            self._grid_columns(row)
            ctk.CTkLabel(row, text=user["username"], font=theme.font(13, "bold"), text_color=theme.TEXT,
                         anchor="w").grid(row=0, column=0, sticky="w", padx=6, pady=8)
            ctk.CTkLabel(row, text=user["display_name"] or "—", font=theme.font(13), text_color=theme.TEXT,
                         anchor="w").grid(row=0, column=1, sticky="w", padx=6)
            is_admin = user["role"] == "admin"
            ctk.CTkLabel(row, text="Admin" if is_admin else "Tienda", width=70, height=22, corner_radius=6,
                         fg_color="#2a3a5c" if is_admin else "#203a2e",
                         text_color=theme.ACCENT if is_admin else theme.ONLINE,
                         font=theme.font(11, "bold")).grid(row=0, column=2, sticky="w", padx=6)
            ctk.CTkLabel(row, text="Activo" if user["active"] else "Inactivo", font=theme.font(12),
                         text_color=theme.TEXT if user["active"] else theme.MUTED,
                         anchor="w").grid(row=0, column=3, sticky="w", padx=6)
            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=4, sticky="e", padx=6)
            theme.button(actions, "ghost", text="Editar", width=72, height=28, font=theme.font(12),
                         command=lambda u=user: self.edit_user(u)).pack(side="left", padx=(0, 6))
            delete = theme.button(actions, "danger", text="Eliminar", width=80, height=28, font=theme.font(12),
                                  command=lambda u=user: self.delete_user(u))
            delete.pack(side="left")
            if user["id"] == self.me["id"]:
                delete.configure(state="disabled", fg_color=theme.SURFACE_2)
        if not users:
            ctk.CTkLabel(self.rows, text="No hay usuarios", text_color=theme.MUTED).pack(pady=20)

    def new_user(self) -> None:
        UserDialog(self, self.bridge, self.api, self.refresh)

    def edit_user(self, user: dict) -> None:
        UserDialog(self, self.bridge, self.api, self.refresh, user)

    def delete_user(self, user: dict) -> None:
        def go():
            self.bridge.run_bg(lambda: self.api.delete_user(user["id"]), lambda _: self.refresh(), self._error)

        ConfirmDialog(self, "Eliminar usuario",
                      f"Se eliminará «{user['username']}» y sus PCs registradas. Esta acción no se puede deshacer.",
                      "Eliminar", go)
