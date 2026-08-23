import hashlib
import hmac
import json
import urllib.error
import urllib.request

from . import db
from .whatsapp_settings import get_whatsapp_settings

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def verify_webhook_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Meta signs webhook payloads with X-Hub-Signature-256: sha256=<hex>,
    HMAC'd with the app's App Secret. Verifying this stops anyone who
    discovers the tunnel URL from injecting fake incoming messages."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


class WhatsAppNotConfigured(Exception):
    pass


def _require_settings() -> dict:
    s = get_whatsapp_settings()
    if not s.get("access_token") or not s.get("phone_number_id"):
        raise WhatsAppNotConfigured("WhatsApp isn't configured yet - add it under Connections.")
    return s


def _graph_request(url: str, settings: dict, data: bytes | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data else "GET",
        headers={
            "Authorization": f"Bearer {settings['access_token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def test_connection() -> dict:
    settings = _require_settings()
    url = f"{GRAPH_BASE}/{settings['phone_number_id']}?fields=display_phone_number,verified_name"
    return _graph_request(url, settings)


def send_text(to: str, body: str) -> dict:
    """Reply within an open 24h customer-service window. Cold-starting a
    conversation with someone who hasn't messaged you requires a
    Meta-approved template instead - this is a WhatsApp platform rule,
    not something this code can work around."""
    settings = _require_settings()
    url = f"{GRAPH_BASE}/{settings['phone_number_id']}/messages"
    payload = json.dumps(
        {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    ).encode("utf-8")
    return _graph_request(url, settings, data=payload)


def record_incoming(from_number: str, text: str, raw: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO whatsapp_inbox (from_number, text, raw_json, received_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (from_number, text, json.dumps(raw)),
        )


def parse_webhook_payload(payload: dict) -> list[dict]:
    """Extract {from, text} pairs from Meta's deeply-nested webhook shape."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                text = msg.get("text", {}).get("body", "")
                out.append({"from": msg.get("from", ""), "text": text})
    return out


def list_inbox(limit: int = 100) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, from_number, text, received_at FROM whatsapp_inbox "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
