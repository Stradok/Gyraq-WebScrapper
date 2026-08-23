import secrets
import threading
import time

TTL_SECONDS = 600  # 10 minutes

_lock = threading.Lock()
_codes: dict[str, float] = {}  # code -> expires_at (unix time)


def create_pairing_code() -> str:
    code = secrets.token_urlsafe(16)
    with _lock:
        _cleanup_locked()
        _codes[code] = time.time() + TTL_SECONDS
    return code


def consume_pairing_code(code: str) -> bool:
    """Single-use: valid codes are removed the moment they're checked,
    whether or not they turn out to be expired."""
    with _lock:
        expires_at = _codes.pop(code, None)
    return expires_at is not None and time.time() < expires_at


def _cleanup_locked() -> None:
    now = time.time()
    for c in [c for c, exp in _codes.items() if exp < now]:
        del _codes[c]
