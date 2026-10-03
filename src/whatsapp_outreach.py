"""Sending a drafted WhatsApp message: picks which of our numbers to send
from, and whether it can go as a free-form reply or must open the
conversation with an approved template.

Rules enforced here, because Meta enforces them anyway and a mistake costs
the number's reputation:
  - free-form text only inside the 24h window after the person messaged us;
  - otherwise only an approved template, and only to people marked opted in;
  - a per-number daily cap on template sends.
"""
import re

from . import db
from .company_profile import get_company_profile
from .contacts import is_opted_in
from .whatsapp import (
    normalize_whatsapp_number,
    record_outgoing,
    send_template,
    send_text,
)
from .whatsapp_settings import get_numbers


class OutreachBlocked(Exception):
    """A send we refuse on purpose; the message is shown to the user."""


def route_number(to_digits: str) -> dict | None:
    """+92 numbers go out from the Pakistan number, everything else from the
    international one. Falls back to any configured number."""
    numbers = get_numbers()
    if not numbers:
        return None
    region = "pk" if to_digits.startswith("92") else "intl"
    for n in numbers:
        if n["region"] == region:
            return n
    return numbers[0]


def window_open(to_digits: str) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM whatsapp_inbox WHERE from_number = ? "
            "AND received_at >= datetime('now', '-24 hours') LIMIT 1",
            (to_digits,),
        ).fetchone()
    return row is not None


def last_inbound_number_id(to_digits: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT phone_number_id FROM whatsapp_inbox WHERE from_number = ? "
            "AND phone_number_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (to_digits,),
        ).fetchone()
    return row["phone_number_id"] if row else None


def sent_today(phone_number_id: str) -> int:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM whatsapp_outbox WHERE phone_number_id = ? "
            "AND kind = 'template' AND status = 'sent' AND created_at >= date('now')",
            (phone_number_id,),
        ).fetchone()
    return row["c"]


def _param(value: str | None, fallback: str) -> str:
    # Template variables can't contain newlines/tabs or long runs of spaces.
    text = re.sub(r"\s+", " ", value or "").strip() or fallback
    return text[:60]


def send_draft(draft: dict) -> None:
    to = normalize_whatsapp_number(draft["to"])
    if not to:
        raise OutreachBlocked(f"{draft['to']!r} isn't a valid phone number.")

    # Inside the 24h window: a normal reply from the number they wrote to.
    if window_open(to):
        number_id = last_inbound_number_id(to) or (route_number(to) or {}).get("phone_number_id")
        send_text(to, draft["body"], number_id)
        record_outgoing(to, draft["body"], "sent", phone_number_id=number_id)
        return

    number = route_number(to)
    if number is None:
        raise OutreachBlocked("No WhatsApp number is configured - add one under Connections.")
    if not number.get("template_name"):
        raise OutreachBlocked(
            f"No approved template set for the {number['label']} number. "
            "WhatsApp only allows a template as a first message."
        )
    if not is_opted_in(to):
        raise OutreachBlocked(
            "Not marked as opted in. Only message people who agreed to hear from you on WhatsApp."
        )
    if sent_today(number["phone_number_id"]) >= number["daily_cap"]:
        raise OutreachBlocked(
            f"Daily limit of {number['daily_cap']} template messages reached for the {number['label']} number."
        )

    values = {
        "business_name": _param(draft.get("business_name"), "there"),
        "company_name": _param(get_company_profile().get("company_name"), "our team"),
    }
    params = [values[f] for f in number["template_params"]]
    label = f"[template {number['template_name']}] " + ", ".join(params)
    try:
        send_template(
            to, number["phone_number_id"], number["template_name"], number["template_language"], params
        )
    except Exception as e:
        record_outgoing(
            to, label, "failed", f"{type(e).__name__}: {e}",
            phone_number_id=number["phone_number_id"], kind="template",
        )
        raise
    record_outgoing(to, label, "sent", phone_number_id=number["phone_number_id"], kind="template")
