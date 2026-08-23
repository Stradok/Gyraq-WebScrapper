import logging
import smtplib

import dns.resolver

from .mail_settings import get_mail_settings

log = logging.getLogger(__name__)

_TIMEOUT_S = 5


def _mx_hosts(domain: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=_TIMEOUT_S)
        return [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda r: r.preference)]
    except Exception:
        return []


def _probe_sender() -> str:
    # A real, deliverable sender domain gets a more honest answer than a
    # made-up one - some servers reject MAIL FROM from a sender domain
    # that can't itself receive mail, which would make every check
    # inconclusive regardless of whether the target mailbox is real.
    settings = get_mail_settings()
    return settings.get("from_email") or settings.get("smtp_user") or "verify@localhost"


def mailbox_exists(email: str) -> bool | None:
    """Best-effort SMTP RCPT-TO probe - connects to the domain's real mail
    server and asks if the mailbox exists, without ever sending DATA (no
    email is actually sent by this).

    Returns False ONLY on an explicit, permanent (5xx) rejection - the
    mailbox genuinely doesn't exist there right now. Returns True/None for
    everything else (looks valid, or the check itself was inconclusive: no
    MX record, connection blocked, greylisted, a catch-all domain that
    accepts any address). Never treat "couldn't verify" as "invalid" - a
    real, working address must never get silently dropped just because
    verification itself failed.
    """
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1]

    # Only the top-priority MX host, and a short timeout - this runs once
    # per candidate email in an already-long per-business pipeline, so a
    # slow/unresponsive server must never be allowed to stall a scrape.
    for host in _mx_hosts(domain)[:1]:
        try:
            with smtplib.SMTP(host, 25, timeout=_TIMEOUT_S) as smtp:
                code, _ = smtp.ehlo()
                if code >= 400:
                    code, _ = smtp.helo()
                if code >= 400:
                    continue

                code, _ = smtp.mail(_probe_sender())
                if code >= 400:
                    continue

                code, message = smtp.rcpt(email)
                if code in (550, 551, 553):
                    log.info("Mailbox check: %s rejected by %s (%r)", email, host, message)
                    return False
                return True
        except Exception:
            continue

    return None
