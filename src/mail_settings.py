import json

from . import db

SETTINGS_KEY = "mail"

DEFAULTS = {
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_use_tls": True,
    "imap_host": "",
    "imap_port": 993,
    "imap_user": "",
    "imap_password": "",
    "imap_use_ssl": True,
    "from_name": "Gyraq",
    "from_email": "",
}

PROVIDER_PRESETS = {
    "gmail": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_use_ssl": True,
    },
    "outlook": {
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_use_ssl": True,
    },
}


def get_mail_settings() -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    merged = dict(DEFAULTS)
    if row:
        merged.update(json.loads(row["value"]))
    return merged


def save_mail_settings(values: dict) -> dict:
    current = get_mail_settings()
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


def masked_mail_settings() -> dict:
    s = dict(get_mail_settings())
    s["smtp_password"] = "set" if s.get("smtp_password") else ""
    s["imap_password"] = "set" if s.get("imap_password") else ""
    return s
