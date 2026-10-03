import json

from . import db

SETTINGS_KEY = "whatsapp"

DEFAULTS = {
    "access_token": "",
    "phone_number_id": "",  # legacy single-number field, still honoured
    "waba_id": "",
    "verify_token": "",
    "app_secret": "",
    "numbers": [],
}

REGIONS = ("pk", "intl")
TEMPLATE_FIELDS = ("business_name", "company_name")
DEFAULT_DAILY_CAP = 50


def get_whatsapp_settings() -> dict:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    merged = dict(DEFAULTS)
    if row:
        merged.update(json.loads(row["value"]))
    return merged


def clean_numbers(raw: list) -> list[dict]:
    """Validate/normalise the numbers list coming from the UI."""
    out = []
    for n in raw or []:
        phone_id = str(n.get("phone_number_id") or "").strip()
        if not phone_id:
            continue
        region = n.get("region") if n.get("region") in REGIONS else "intl"
        try:
            cap = max(1, min(1000, int(n.get("daily_cap") or DEFAULT_DAILY_CAP)))
        except (TypeError, ValueError):
            cap = DEFAULT_DAILY_CAP
        params = [p for p in (n.get("template_params") or []) if p in TEMPLATE_FIELDS]
        out.append(
            {
                "label": str(n.get("label") or "").strip() or ("Pakistan" if region == "pk" else "International"),
                "region": region,
                "phone_number_id": phone_id,
                "daily_cap": cap,
                "template_name": str(n.get("template_name") or "").strip(),
                "template_language": str(n.get("template_language") or "en").strip() or "en",
                "template_params": params,
            }
        )
    return out


def get_numbers(settings: dict | None = None) -> list[dict]:
    """Our WhatsApp numbers. Falls back to the legacy single phone_number_id
    so installs configured before multi-number support keep working."""
    s = settings or get_whatsapp_settings()
    numbers = s.get("numbers") or []
    if numbers:
        return numbers
    if s.get("phone_number_id"):
        return [
            {
                "label": "Default",
                "region": "intl",
                "phone_number_id": s["phone_number_id"],
                "daily_cap": DEFAULT_DAILY_CAP,
                "template_name": "",
                "template_language": "en",
                "template_params": [],
            }
        ]
    return []


def save_whatsapp_settings(values: dict) -> dict:
    current = get_whatsapp_settings()
    for key, value in values.items():
        if key not in DEFAULTS or value is None:
            continue
        current[key] = clean_numbers(value) if key == "numbers" else value
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
    s["app_secret"] = "set" if s.get("app_secret") else ""
    s["numbers"] = get_numbers(s)
    return s
