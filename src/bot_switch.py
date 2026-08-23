import json

from . import db

SETTINGS_KEY = "chatbot_enabled"


def is_bot_enabled() -> bool:
    """Global kill switch for the WhatsApp chatbot. Defaults to ON so an
    unconfigured install behaves the same as before this existed; when off,
    inbound messages are still recorded and linked to contacts, just never
    auto-replied to."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    if row:
        return bool(json.loads(row["value"]).get("enabled", True))
    return True


def set_bot_enabled(enabled: bool) -> bool:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, json.dumps({"enabled": bool(enabled)})),
        )
    return bool(enabled)
