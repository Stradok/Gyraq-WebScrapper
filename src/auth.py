import os
import secrets
import stat

from . import config, db

TOKEN_KEY = "auth_token"
TOKEN_FILE = os.path.join(os.path.dirname(config.DB_FILE) or ".", ".auth_token")


def get_or_create_token() -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (TOKEN_KEY,)).fetchone()
        if row:
            token = row["value"]
        else:
            token = secrets.token_urlsafe(24)
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (TOKEN_KEY, token),
            )

    _write_token_file(token)
    return token


def _write_token_file(token: str) -> None:
    """Mirrors the token to a plain file so local tools (the Electron app)
    can read it directly off disk without an HTTP round-trip - useful since
    Docker's NAT/proxying makes source-IP-based trust unreliable."""
    try:
        os.makedirs(os.path.dirname(TOKEN_FILE) or ".", exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def verify_token(supplied: str | None) -> bool:
    if not supplied:
        return False
    return secrets.compare_digest(supplied, get_or_create_token())
