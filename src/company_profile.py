import json

from . import db

SETTINGS_KEY = "company_profile"

DEFAULTS = {
    "company_name": "Gyraq",
    "website": "",
    "description": "",
}


def get_company_profile() -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    merged = dict(DEFAULTS)
    if row:
        merged.update(json.loads(row["value"]))
    return merged


def save_company_profile(values: dict) -> dict:
    current = get_company_profile()
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
