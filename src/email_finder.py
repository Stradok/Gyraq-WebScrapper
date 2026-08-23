import logging
import re
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

JUNK_DOMAINS = (
    "wixpress.com",
    "sentry.io",
    "schema.org",
    "example.com",
    "godaddy.com",
    "domain.com",
    "yourdomain.com",
    "w3.org",
)

CONTACT_PATHS = ("contact", "contact-us", "contactus")


def _is_junk(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return any(domain == j or domain.endswith("." + j) for j in JUNK_DOMAINS)


def _extract_from_page(page) -> str | None:
    try:
        mailto = page.locator('a[href^="mailto:"]').first
        if mailto.count():
            href = mailto.get_attribute("href", timeout=2000) or ""
            candidate = href[len("mailto:") :].split("?")[0].strip()
            if candidate and not _is_junk(candidate):
                return candidate
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        return None

    for match in EMAIL_RE.findall(body_text):
        if not _is_junk(match):
            return match
    return None


def find_email(context: BrowserContext, website: str | None, timeout_ms: int = 12000) -> str | None:
    if not website:
        return None

    page = context.new_page()
    page.set_default_navigation_timeout(timeout_ms)
    page.set_default_timeout(timeout_ms)
    try:
        try:
            page.goto(website, wait_until="domcontentloaded")
        except Exception:
            return None

        email = _extract_from_page(page)
        if email:
            return email

        for path in CONTACT_PATHS:
            try:
                page.goto(urljoin(website, path), wait_until="domcontentloaded")
            except Exception:
                continue
            email = _extract_from_page(page)
            if email:
                return email

        return None
    except Exception:
        log.warning("Email lookup failed for %r", website, exc_info=True)
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass
