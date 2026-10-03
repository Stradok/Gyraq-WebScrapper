import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request

from . import db
from .whatsapp_settings import get_numbers, get_whatsapp_settings

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def normalize_whatsapp_number(phone: str | None) -> str | None:
    """The Graph API wants digits only, no "+", no spaces/dashes/parens -
    Google Maps gives phone numbers like "+92 345 8456753"."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits if len(digits) >= 8 else None


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
    if not s.get("access_token") or not get_numbers(s):
        raise WhatsAppNotConfigured("WhatsApp isn't configured yet - add it under Connections.")
    return s


def _phone_id(settings: dict, phone_number_id: str | None) -> str:
    """The number to send from; defaults to the first configured one."""
    return phone_number_id or get_numbers(settings)[0]["phone_number_id"]


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


def test_connection() -> list[dict]:
    """Check every configured number; one result per number."""
    settings = _require_settings()
    results = []
    for n in get_numbers(settings):
        url = f"{GRAPH_BASE}/{n['phone_number_id']}?fields=display_phone_number,verified_name,quality_rating"
        try:
            results.append({"label": n["label"], "ok": True, "info": _graph_request(url, settings)})
        except Exception as e:
            results.append({"label": n["label"], "ok": False, "error": f"{type(e).__name__}: {e}"})
    return results


def send_template(to: str, phone_number_id: str, name: str, language: str, params: list[str]) -> dict:
    """Open a conversation with an approved template - the only thing Meta
    allows as a first message to someone who hasn't written to us."""
    settings = _require_settings()
    template: dict = {"name": name, "language": {"code": language}}
    if params:
        template["components"] = [
            {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
        ]
    url = f"{GRAPH_BASE}/{_phone_id(settings, phone_number_id)}/messages"
    payload = json.dumps(
        {"messaging_product": "whatsapp", "to": to, "type": "template", "template": template}
    ).encode("utf-8")
    return _graph_request(url, settings, data=payload)


def send_text(to: str, body: str, phone_number_id: str | None = None) -> dict:
    """Reply within an open 24h customer-service window. Cold-starting a
    conversation with someone who hasn't messaged you requires a
    Meta-approved template instead - this is a WhatsApp platform rule,
    not something this code can work around."""
    settings = _require_settings()
    url = f"{GRAPH_BASE}/{_phone_id(settings, phone_number_id)}/messages"
    payload = json.dumps(
        {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
    ).encode("utf-8")
    return _graph_request(url, settings, data=payload)


def record_incoming(from_number: str, text: str, raw: dict, phone_number_id: str | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO whatsapp_inbox (from_number, text, raw_json, received_at, phone_number_id) "
            "VALUES (?, ?, ?, datetime('now'), ?)",
            (from_number, text, json.dumps(raw), phone_number_id),
        )


def parse_webhook_payload(payload: dict) -> list[dict]:
    """Extract {from, text} pairs from Meta's deeply-nested webhook shape."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # Which of our numbers was messaged - replies must come from it.
            phone_id = value.get("metadata", {}).get("phone_number_id")
            for msg in value.get("messages", []):
                text = msg.get("text", {}).get("body", "")
                out.append({"from": msg.get("from", ""), "text": text, "phone_number_id": phone_id})
    return out


def list_inbox(limit: int = 100) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, from_number, text, received_at FROM whatsapp_inbox "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def record_outgoing(
    phone_number: str,
    text: str,
    status: str,
    error: str | None = None,
    duration_ms: int | None = None,
    phone_number_id: str | None = None,
    kind: str = "text",
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO whatsapp_outbox (phone_number, text, status, error, created_at, duration_ms, "
            "phone_number_id, kind) VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?)",
            (phone_number, text, status, error, duration_ms, phone_number_id, kind),
        )


def get_thread(phone_number: str, limit: int = 20) -> list[dict]:
    """Full conversation with one contact, both directions, oldest first -
    what the bot sees as context and what the Contacts UI displays."""
    with db.connect() as conn:
        incoming = conn.execute(
            "SELECT text, received_at AS ts FROM whatsapp_inbox "
            "WHERE from_number = ? ORDER BY id DESC LIMIT ?",
            (phone_number, limit),
        ).fetchall()
        outgoing = conn.execute(
            "SELECT text, created_at AS ts, status, duration_ms FROM whatsapp_outbox "
            "WHERE phone_number = ? ORDER BY id DESC LIMIT ?",
            (phone_number, limit),
        ).fetchall()

    thread = [{"direction": "in", "text": r["text"], "ts": r["ts"]} for r in incoming]
    thread += [
        {
            "direction": "out",
            "text": r["text"],
            "ts": r["ts"],
            "status": r["status"],
            "duration_ms": r["duration_ms"],
        }
        for r in outgoing
    ]
    thread.sort(key=lambda m: m["ts"] or "")
    return thread[-limit:]
