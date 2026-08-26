import hashlib
import hmac
import json
import secrets
import threading
import time

from . import db

PIN_KEY = "access_pin"

_PBKDF2_ROUNDS = 200_000

# A short PIN is only ~10k combinations, so without throttling it's
# guessable in seconds by a script on the same network.
#
# Deliberately a delay rather than a quick hard lockout: behind Docker's
# NAT every client reports the same source IP (verified - all requests
# arrive from the gateway address), so "lock out this IP" is really "lock
# out everyone". A hard lockout would let anyone on the WiFi keep the
# owner out by spamming wrong PINs. A growing per-attempt delay makes
# brute force impractical (10k guesses at 3s each is over 8 hours) while
# a legitimate user mistyping once only ever waits a moment.
FAILURE_DELAY_SECONDS = 0.75
MAX_DELAY_SECONDS = 3.0

# Backstop against a fast parallel script - high enough that ordinary
# mistyping never reaches it, short enough that it isn't a useful DoS.
MAX_ATTEMPTS = 20
LOCKOUT_SECONDS = 60

# Failures decay, so yesterday's typos don't add up into a lockout.
FAILURE_WINDOW_SECONDS = 900

_lock = threading.Lock()
_failures: dict[str, tuple[int, float, float]] = {}  # ip -> (count, locked_until, last_failure)


def _hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _PBKDF2_ROUNDS).hex()


def set_pin(pin: str) -> None:
    """Stored salted+hashed rather than in the clear - the DB also holds
    mail credentials, so a leaked copy shouldn't hand over the PIN too."""
    pin = (pin or "").strip()
    if not pin:
        raise ValueError("PIN can't be empty")
    salt = secrets.token_bytes(16)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (PIN_KEY, json.dumps({"salt": salt.hex(), "hash": _hash_pin(pin, salt)})),
        )


def clear_pin() -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (PIN_KEY,))


def has_pin() -> bool:
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM settings WHERE key = ?", (PIN_KEY,)).fetchone() is not None


def _current_failures(client_ip: str) -> tuple[int, float]:
    """(count, locked_until), with stale failures outside the window
    treated as expired."""
    count, locked_until, last = _failures.get(client_ip, (0, 0.0, 0.0))
    if last and time.time() - last > FAILURE_WINDOW_SECONDS:
        return 0, 0.0
    return count, locked_until


def lockout_remaining(client_ip: str) -> int:
    with _lock:
        _, locked_until = _current_failures(client_ip)
    remaining = int(locked_until - time.time())
    return remaining if remaining > 0 else 0


def _record_failure(client_ip: str) -> float:
    """Records the failure and returns how long the caller should wait
    before answering."""
    with _lock:
        count, _ = _current_failures(client_ip)
        count += 1
        now = time.time()
        locked_until = now + LOCKOUT_SECONDS if count >= MAX_ATTEMPTS else 0.0
        _failures[client_ip] = (count, locked_until, now)
    return min(count * FAILURE_DELAY_SECONDS, MAX_DELAY_SECONDS)


def clear_failures(client_ip: str) -> None:
    with _lock:
        _failures.pop(client_ip, None)


def verify_pin(pin: str, client_ip: str) -> bool:
    """Returns True only on a correct PIN from a client that isn't locked
    out. On a wrong PIN this sleeps for a growing delay before returning,
    which is what actually makes brute-forcing a short PIN impractical."""
    if lockout_remaining(client_ip):
        return False

    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (PIN_KEY,)).fetchone()
    if not row:
        return False

    stored = json.loads(row["value"])
    candidate = _hash_pin((pin or "").strip(), bytes.fromhex(stored["salt"]))
    if hmac.compare_digest(candidate, stored["hash"]):
        clear_failures(client_ip)
        return True

    time.sleep(_record_failure(client_ip))
    return False
