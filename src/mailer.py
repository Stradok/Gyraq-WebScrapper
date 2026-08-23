import imaplib
import smtplib
import ssl
from email.message import EmailMessage

from .mail_settings import get_mail_settings


class MailNotConfigured(Exception):
    pass


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
