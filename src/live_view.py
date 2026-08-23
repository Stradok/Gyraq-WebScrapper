import threading
import time

_lock = threading.Lock()
_latest: bytes | None = None
_latest_at: float = 0.0


def set_frame(data: bytes) -> None:
    global _latest, _latest_at
    with _lock:
        _latest = data
        _latest_at = time.time()


def get_frame() -> tuple[bytes | None, float]:
    with _lock:
        return _latest, _latest_at
