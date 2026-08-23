import logging
import re
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext

from .mailbox_verify import mailbox_exists

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

# Major consumer providers a typo'd domain most often means to be - listed
# here so a near-miss (one edit away, e.g. "gamil.com") can be caught before
# it ever reaches a send attempt. Not every wrong email is catchable this
# way (a wrong-but-valid mailbox slips through no matter what), but a typo
# of one of these specific well-known domains is the single most common
# case, verified against a real bounce (skinsavvy640@gamil.com).
_MAJOR_EMAIL_DOMAINS = (
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "aol.com",
    "protonmail.com",
)

# Real, currently-operating domains that happen to be within edit distance
# 2 of one of the above - without this, a legitimate address would get
# silently treated as a typo (a false positive here is worse than the typo
# itself: a real, working email that would have been fine silently never
# gets a draft, with no bounce or any other visible signal that anything
# was skipped).
_LEGITIMATE_LOOKALIKES = frozenset(
    {
        "mail.com",
        "googlemail.com",
        "ymail.com",
        "live.com",
        "msn.com",
        "yahoo.co.uk",
        "yahoo.co.in",
        "yahoo.ca",
        "yahoo.com.au",
        "hotmail.co.uk",
        "hotmail.fr",
        "outlook.co.uk",
        "outlook.de",
        "aol.co.uk",
    }
)


def _edit_distance_le(a: str, b: str, max_dist: int) -> bool:
    if abs(len(a) - len(b)) > max_dist:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1] <= max_dist


def _is_likely_typo_domain(domain: str) -> bool:
    if domain in _LEGITIMATE_LOOKALIKES:
        return False
    return any(
        domain != major and _edit_distance_le(domain, major, 2)
        for major in _MAJOR_EMAIL_DOMAINS
    )


def _is_junk(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    if any(domain == j or domain.endswith("." + j) for j in JUNK_DOMAINS):
        return True
    return _is_likely_typo_domain(domain)


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
        if email and mailbox_exists(email) is not False:
            return email

        for path in CONTACT_PATHS:
            try:
                page.goto(urljoin(website, path), wait_until="domcontentloaded")
            except Exception:
                continue
            email = _extract_from_page(page)
            if email and mailbox_exists(email) is not False:
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
