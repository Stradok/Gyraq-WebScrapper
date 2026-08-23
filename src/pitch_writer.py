import json
import logging
import urllib.request

from . import config
from .company_profile import get_company_profile
from .models import Business
from .prompt_settings import get_ollama_model, get_system_prompt

log = logging.getLogger(__name__)

FOOTER = '\n\n—\n{company_name}\n{address}\nDon\'t want to hear from us? Just reply "unsubscribe".'


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
        company_name = get_company_profile().get("company_name") or "Gyraq"
        body = parsed["body"] + FOOTER.format(
            company_name=company_name, address=config.COMPANY_ADDRESS
        )
        return {"pitch": parsed.get("pitch"), "subject": subject, "body": body}
    except Exception:
        log.warning("Pitch generation failed for %r", biz.name, exc_info=True)
        return None
