import json

from . import db

SETTINGS_KEY = "whatsapp"

DEFAULTS = {
    "access_token": "",
    "phone_number_id": "",
    "waba_id": "",
    "verify_token": "",
}


def get_whatsapp_settings() -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    merged = dict(DEFAULTS)
    if row:
        merged.update(json.loads(row["value"]))
    return merged


def save_whatsapp_settings(values: dict) -> dict:
    current = get_whatsapp_settings()
    for key, value in values.items():
        if key in DEFAULTS and value is not None:
            current[key] = value
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, json.dumps(current)),
        )
    return current


def masked_whatsapp_settings() -> dict:
    s = dict(get_whatsapp_settings())
    s["access_token"] = "set" if s.get("access_token") else ""
    return s
