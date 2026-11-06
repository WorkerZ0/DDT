import customtkinter as ctk

BG = "#0e1014"
SURFACE = "#161920"
SURFACE_2 = "#1d212a"
BORDER = "#272c37"
TEXT = "#e7e9ee"
MUTED = "#8b91a0"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#3b78e8"
ONLINE = "#2fd17a"
OFFLINE = "#5b6170"
WARN = "#f2b33d"
LIVE = "#ff4d4f"
DANGER = "#e5484d"
DANGER_HOVER = "#c63b40"

FAMILY = "Segoe UI"


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def entry(master, **kw) -> ctk.CTkEntry:
    opts = dict(height=38, corner_radius=8, fg_color=SURFACE_2, border_color=BORDER,
                text_color=TEXT, placeholder_text_color=MUTED, font=font(13))
    opts.update(kw)
    return ctk.CTkEntry(master, **opts)


def button(master, kind: str = "primary", **kw) -> ctk.CTkButton:
    colors = {
        "primary": (ACCENT, ACCENT_HOVER, "#ffffff"),
        "ghost": (SURFACE_2, BORDER, TEXT),
        "danger": (DANGER, DANGER_HOVER, "#ffffff"),
    }[kind]
    opts = dict(height=36, corner_radius=8, fg_color=colors[0], hover_color=colors[1],
                text_color=colors[2], font=font(13, "bold"))
    opts.update(kw)
    return ctk.CTkButton(master, **opts)
