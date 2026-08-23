import re
from datetime import datetime, timezone

from . import db
from .drafts_store import list_drafts
from .mail_settings import get_mail_settings

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _row_to_dict(row) -> dict:
    return {
        "phone_number": row["phone_number"],
        "email": row["email"],
        "business_name": row["business_name"],
        "pitch": row["pitch"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_contact(phone_number: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE phone_number = ?", (phone_number,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_contacts(query: str | None = None) -> list[dict]:
    with db.connect() as conn:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                "SELECT * FROM contacts WHERE phone_number LIKE ? OR email LIKE ? "
                "OR business_name LIKE ? OR notes LIKE ? ORDER BY updated_at DESC",
                (like, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM contacts ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def upsert_contact(phone_number: str, **fields) -> dict:
    now = _now()
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT phone_number FROM contacts WHERE phone_number = ?", (phone_number,)
        ).fetchone()
        if existing:
            cols = [f"{k} = ?" for k in fields if fields[k] is not None]
            if cols:
                values = [v for v in fields.values() if v is not None] + [now, phone_number]
                conn.execute(
                    f"UPDATE contacts SET {', '.join(cols)}, updated_at = ? WHERE phone_number = ?",
                    values,
                )
            else:
                conn.execute(
                    "UPDATE contacts SET updated_at = ? WHERE phone_number = ?", (now, phone_number)
                )
        else:
            conn.execute(
                "INSERT INTO contacts (phone_number, email, business_name, pitch, notes, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    phone_number,
                    fields.get("email"),
                    fields.get("business_name"),
                    fields.get("pitch"),
                    fields.get("notes"),
                    now,
                    now,
                ),
            )
    return get_contact(phone_number)


def _match_draft_by_recipient(value: str) -> dict | None:
    """Find the most recent draft (any channel) sent to this exact
    recipient (phone digits or email), used to backfill a contact's
    business_name/pitch/email from prior outreach we already did."""
    if not value:
        return None
    for d in reversed(list_drafts()):
        to = d.get("to") or ""
        if d.get("channel") == "whatsapp":
            if _digits(to) == _digits(value):
                return d
        elif to.lower() == value.lower():
            return d
    return None


def extract_email(text: str) -> str | None:
    """First email mentioned that isn't our own address - people often
    quote/reference "the email you sent to X" or a reply-chain footer, and
    that's never the customer's own email."""
    settings = get_mail_settings()
    ours = {(settings.get("smtp_user") or "").lower(), (settings.get("from_email") or "").lower()}
    ours.discard("")
    for m in EMAIL_RE.finditer(text or ""):
        if m.group(0).lower() not in ours:
            return m.group(0)
    return None


def link_contact(phone_number: str, message_text: str = "") -> dict:
    """Called whenever an inbound WhatsApp message arrives. Creates the
    contact if new, then tries to backfill business_name/pitch/email from
    whatever we already know: a prior draft sent to this same number, or -
    if they mention their email in the message itself, a rare but real
    case when someone messages from a different/new number than the one
    we originally scraped - a prior draft sent to that email."""
    contact = get_contact(phone_number)
    if contact is None:
        contact = upsert_contact(phone_number)

    updates = {}
    if not contact.get("email"):
        mentioned_email = extract_email(message_text)
        if mentioned_email:
            updates["email"] = mentioned_email

    if not contact.get("business_name"):
        match = _match_draft_by_recipient(phone_number)
        if match is None and updates.get("email"):
            match = _match_draft_by_recipient(updates["email"])
        elif match is None and contact.get("email"):
            match = _match_draft_by_recipient(contact["email"])
        if match:
            updates["business_name"] = match.get("business_name")
            updates["pitch"] = match.get("pitch")
            if not updates.get("email") and not contact.get("email") and match.get("channel") != "whatsapp":
                updates["email"] = match.get("to")

    if updates:
        contact = upsert_contact(phone_number, **updates)
    return contact
