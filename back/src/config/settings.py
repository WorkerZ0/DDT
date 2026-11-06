import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
ADMIN_TOKEN_HOURS = _int("ADMIN_TOKEN_HOURS", 12)
AGENT_TOKEN_DAYS = _int("AGENT_TOKEN_DAYS", 365)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

DB_PATH = os.getenv("DB_PATH", "/data/ddt.db")

# Miniatura siempre; en vivo solo mientras algún admin mira esa PC
THUMB_INTERVAL = _float("THUMB_INTERVAL", 5)
THUMB_WIDTH = _int("THUMB_WIDTH", 480)
THUMB_QUALITY = _int("THUMB_QUALITY", 40)
# Si un visor muestra la PC en una tarjeta grande pide la miniatura a ese ancho (hasta este tope)
THUMB_MAX_WIDTH = _int("THUMB_MAX_WIDTH", 1920)
THUMB_HD_QUALITY = _int("THUMB_HD_QUALITY", 55)
LIVE_FPS = _float("LIVE_FPS", 8)
LIVE_WIDTH = _int("LIVE_WIDTH", 3840)    # tope para varios monitores unidos
LIVE_HEIGHT = _int("LIVE_HEIGHT", 1080)  # 1080 = resolución nativa de un monitor Full HD
LIVE_QUALITY = _int("LIVE_QUALITY", 50)

# Video H.264 para PCs con codificador por hardware; las demás siguen con JPEG a LIVE_FPS
VIDEO_ENABLED = os.getenv("VIDEO_ENABLED", "1") == "1"
VIDEO_FPS = _int("VIDEO_FPS", 25)
VIDEO_BITRATE = _int("VIDEO_BITRATE", 2_500_000)  # bps para un monitor 1080p (se escala por área)

MAX_FRAME_BYTES = _int("MAX_FRAME_BYTES", 3_000_000)
WS_AUTH_TIMEOUT = 10
