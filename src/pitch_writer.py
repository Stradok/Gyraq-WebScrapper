import json
import logging
import re
import urllib.request

from . import config
from .company_profile import get_company_profile
from .models import Business
from .prompt_settings import get_ollama_model, get_system_prompt

log = logging.getLogger(__name__)

_SCHEME_RE = re.compile(r"^\w+://", re.IGNORECASE)


def _bare_domain(website: str) -> str:
    """Strip scheme/path/www so the footer can name the company without
    the deliverability guard ever seeing something that looks like a URL -
    a bare domain like "gyraq.com" doesn't match _URL_RE below."""
    domain = _SCHEME_RE.sub("", (website or "").strip()).split("/")[0]
    return domain[4:] if domain.lower().startswith("www.") else domain


# The sign-off is deterministic, not left to the model - verified live that
# a local model skips "Always sign off as X" some of the time even when
# told to, so this is appended in code instead of trusted to prompt-following.
# No physical address (dropped after a placeholder leaked into a real send) -
# just the team name and, if set, the bare company domain.
def _footer(company_name: str, website: str) -> str:
    domain = _bare_domain(website)
    domain_line = f"\n{domain}" if domain else ""
    return f'\n\nThe {company_name} Team{domain_line}\n\nDon\'t want to hear from us? Just reply "unsubscribe".'

# Hard backstop behind the prompt's own deliverability instructions - the
# prompt is best-effort (a local model won't follow it 100% of the time),
# so anything that slips through here just means no draft gets created for
# that business (same as any other pitch-generation failure), never a sent
# email with a link or a classic spam phrase in it. Only phrases that are
# essentially never legitimate in this context - ambiguous single words
# like "free" or "opportunity" are left to the prompt alone, since rejecting
# every draft that happens to contain "feel free to reply" would silently
# throw away far more good drafts than bad ones.
_SPAM_PHRASE_RE = re.compile(
    r"\b(act now|limited time|no obligation|risk[- ]free|click here|"
    r"double your revenue|100% free|money[- ]back guarantee|special offer)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(https?://|www\.|\bbit\.ly\b|\btinyurl\b|\bt\.co\b)", re.IGNORECASE)

# The prompt tells the model not to write its own closing - this mops up
# the rare case where it does anyway, so it never doubles up with the
# deterministic sign-off FOOTER adds.
_SIGNOFF_TAIL_RE = re.compile(
    r"\s*(the\s+[\w&' -]{2,30}?\s+team|best regards|kind regards|warm regards|"
    r"best|regards|sincerely|thank you|thanks|cheers)[,.]?\s*$",
    re.IGNORECASE,
)


def _strip_model_signoff(body: str) -> str:
    stripped = _SIGNOFF_TAIL_RE.sub("", body).rstrip()
    return stripped or body


def _violates_deliverability_rules(subject: str, body: str) -> str | None:
    combined = f"{subject}\n{body}"
    m = _SPAM_PHRASE_RE.search(combined)
    if m:
        return f"spam phrase: {m.group(0)!r}"
    if _URL_RE.search(body):
        return "contains a link/URL"
    return None


def _build_system_prompt() -> str:
    profile = get_company_profile()
    facts = []
    if profile.get("company_name"):
        facts.append(f"Company: {profile['company_name']}")
    if profile.get("website"):
        facts.append(f"Website: {profile['website']}")
    if profile.get("description"):
        facts.append(f"About the company: {profile['description']}")

    base = get_system_prompt()
    if not facts:
        return base
    preamble = "Facts about who you're writing on behalf of:\n" + "\n".join(facts) + "\n\n"
    return preamble + base


def generate_pitch(biz: Business, reputation: dict | None = None) -> dict | None:
    reputation = reputation or {}
    user_content = json.dumps(
        {
            "name": biz.name,
            "category": biz.category,
            "rating": biz.rating,
            "review_count": biz.review_count,
            "address": biz.address,
            "has_website": bool(biz.website),
            "reviews": [r.text for r in biz.reviews if r.text],
            "reddit_mentions": [
                {"title": r["title"], "snippet": r["snippet"]}
                for r in reputation.get("reddit", [])
            ],
            "other_mentions": [
                {"title": r["title"], "snippet": r["snippet"]}
                for r in reputation.get("reviews", [])
            ],
            "linkedin_mentions": [
                {"title": r["title"], "snippet": r["snippet"]}
                for r in reputation.get("linkedin", [])
            ],
        }
    )

    payload = json.dumps(
        {
            "model": get_ollama_model(),
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": user_content},
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parsed = json.loads(data["message"]["content"])
        subject = parsed["subject"]
        raw_body = _strip_model_signoff(parsed["body"].rstrip())

        violation = _violates_deliverability_rules(subject, raw_body)
        if violation:
            log.warning("Pitch for %r rejected (%s), skipping draft", biz.name, violation)
            return None

        profile = get_company_profile()
        company_name = profile.get("company_name") or "Gyraq"
        body = raw_body + _footer(company_name, profile.get("website") or "")
        return {"pitch": parsed.get("pitch"), "subject": subject, "body": body}
    except Exception:
        log.warning("Pitch generation failed for %r", biz.name, exc_info=True)
        return None
