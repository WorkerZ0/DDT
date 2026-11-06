import time
from collections import defaultdict, deque


class LoginLimiter:
    """Bloquea una clave (ip|usuario) tras varios fallos en la ventana."""

    def __init__(self, max_fails: int = 5, window: float = 300):
        self.max_fails = max_fails
        self.window = window
        self._fails: dict[str, deque] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        fails = self._fails.get(key)
        if not fails:
            return False
        now = time.monotonic()
        while fails and now - fails[0] > self.window:
            fails.popleft()
        if not fails:
            del self._fails[key]
        return len(fails) >= self.max_fails

    def fail(self, key: str) -> None:
        self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_limiter = LoginLimiter()
