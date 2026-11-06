from __future__ import annotations

from PIL import Image, ImageDraw

from shared import theme


def draw_logo(size: int = 64, dot: str | None = theme.ONLINE) -> Image.Image:
    """Monitor con punto de estado. Se usa para la bandeja y el .ico."""
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4 * s, 8 * s, 60 * s, 46 * s), radius=7 * s, fill=theme.SURFACE_2,
                        outline=theme.ACCENT, width=max(1, round(4 * s)))
    d.rectangle((28 * s, 46 * s, 36 * s, 54 * s), fill=theme.ACCENT)
    d.rounded_rectangle((18 * s, 53 * s, 46 * s, 59 * s), radius=3 * s, fill=theme.ACCENT)
    if dot:
        d.ellipse((38 * s, 2 * s, 62 * s, 26 * s), fill=dot, outline=theme.BG, width=max(1, round(3 * s)))
    return img
