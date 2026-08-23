import json
import logging
import urllib.request

from . import config
from .models import Business
from .prompt_settings import get_system_prompt

log = logging.getLogger(__name__)

FOOTER = '\n\n—\nGyraq\n{address}\nDon\'t want to hear from us? Just reply "unsubscribe".'


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
            "model": config.OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": get_system_prompt()},
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
        body = parsed["body"] + FOOTER.format(address=config.COMPANY_ADDRESS)
        return {"pitch": parsed.get("pitch"), "subject": subject, "body": body}
    except Exception:
        log.warning("Pitch generation failed for %r", biz.name, exc_info=True)
        return None
