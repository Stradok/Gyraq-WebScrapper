import email.utils
import imaplib
import logging
import re
import smtplib
import ssl
import time
from email.message import EmailMessage

from .mail_settings import get_mail_settings

log = logging.getLogger(__name__)


class MailNotConfigured(Exception):
    pass


def _find_sent_folder(conn: imaplib.IMAP4) -> str | None:
    """IMAP has no fixed name for the Sent folder - Gmail/modern servers
    advertise it via the RFC 6154 \\Sent special-use flag, but plenty of
    providers (older cPanel/Dovecot setups) don't, so fall back to the
    first folder whose name contains "sent"."""
    typ, folders = conn.list()
    if typ != "OK" or not folders:
        return None
    fallback = None
    for raw in folders:
        if not raw:
            continue
        line = raw.decode(errors="ignore") if isinstance(raw, bytes) else raw
        m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
        if not m:
            continue
        name = m.group(1)
        if "\\sent" in line.lower():
            return name
        if fallback is None and "sent" in name.lower():
            fallback = name
    return fallback


def _save_to_sent(settings: dict, msg_bytes: bytes) -> None:
    """Best-effort only: the email is already delivered via SMTP by the
    time this runs, so a failure here (no IMAP configured, no Sent
    folder found, wrong password, etc.) must never look like a failed
    send - just log it and move on."""
    if not settings.get("imap_host") or not settings.get("imap_user"):
        return
    try:
        host = settings["imap_host"]
        port = int(settings.get("imap_port") or 993)
        user = settings["imap_user"]
        password = settings.get("imap_password") or ""
        conn = (
            imaplib.IMAP4_SSL(host, port, timeout=15)
            if settings.get("imap_use_ssl", True)
            else imaplib.IMAP4(host, port, timeout=15)
        )
        try:
            conn.login(user, password)
            folder = _find_sent_folder(conn)
            if not folder:
                log.warning("Sent an email but found no IMAP Sent folder to file a copy into")
                return
            conn.append(folder, "\\Seen", imaplib.Time2Internaldate(time.time()), msg_bytes)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception:
        log.warning("Failed to save a copy of the sent email to the IMAP Sent folder", exc_info=True)


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_mail_settings()
    if not settings.get("smtp_host") or not settings.get("smtp_user"):
        raise MailNotConfigured("SMTP isn't configured yet - add it under Mail Settings.")

    msg = EmailMessage()
    from_name = settings.get("from_name") or "Gyraq"
    from_email = settings.get("from_email") or settings["smtp_user"]
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg.set_content(body)

    host = settings["smtp_host"]
    port = int(settings.get("smtp_port") or 587)
    user = settings["smtp_user"]
    password = settings.get("smtp_password") or ""

    # Port 465 is implicit TLS (SMTPS) by universal convention - the
    # server expects an encrypted handshake from the very first byte.
    # Sending it a plaintext STARTTLS-style greeting (what the "use TLS"
    # toggle used to trigger regardless of port) makes it hang and then
    # drop the connection - exactly the "unexpectedly closed" failure
    # this fixes. Port 587 (or anything else) is plaintext-then-upgrade,
    # so STARTTLS is correct there when the toggle is on.
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as server:
            server.login(user, password)
            server.send_message(msg)
    elif settings.get("smtp_use_tls", True):
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.login(user, password)
            server.send_message(msg)

    # SMTP submission alone doesn't put a copy in the account's Sent
    # folder - that's a webmail-UI convention, not something the SMTP
    # protocol does for you. File one over IMAP so sent mail actually
    # shows up in the mailbox, not just in this app's own history.
    _save_to_sent(settings, msg.as_bytes())


def test_smtp() -> None:
    settings = get_mail_settings()
    to = settings.get("from_email") or settings.get("smtp_user")
    if not to:
        raise MailNotConfigured("SMTP isn't configured yet - add it under Mail Settings.")
    send_email(to, "Gyraq Lead Scraper - test email", "This is a test email from your mail settings.")


def test_imap() -> None:
    settings = get_mail_settings()
    if not settings.get("imap_host") or not settings.get("imap_user"):
        raise MailNotConfigured("IMAP isn't configured yet - add it under Mail Settings.")

    host = settings["imap_host"]
    port = int(settings.get("imap_port") or 993)
    user = settings["imap_user"]
    password = settings.get("imap_password") or ""

    if settings.get("imap_use_ssl", True):
        conn = imaplib.IMAP4_SSL(host, port, timeout=15)
    else:
        conn = imaplib.IMAP4(host, port, timeout=15)
    try:
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
