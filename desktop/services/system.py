"""Capa de sistema por plataforma. Expone la misma API en Windows y macOS:
single_instance, input_idle_seconds, message_box, enable_autostart, disable_autostart,
write_heartbeat, mark_stopped, clear_stopped, request_update, take_killed_alert."""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from services._system_mac import *  # noqa: F401,F403
else:
    from services._system_win import *  # noqa: F401,F403
