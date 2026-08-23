import json
import logging
import urllib.request

from . import config
from .models import Business

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are writing a short, personalized cold outreach email on behalf of "
    "Gyraq (services@gyraq.com), which helps local businesses with two "
    "services: 1) AI voice agents that act as an automated receptionist/"
    "customer support line - answering calls, taking messages, booking "
    "appointments, working 24/7 with no hold times. 2) Professional website "
    "design/building for businesses with no website or an outdated one. "
    "You'll be given data about one specific local business. Decide which "
    "ONE service fits better: no website or a very basic one -> pitch the "
    "website; reviews mentioning missed calls, slow replies, being hard to "
    "reach, long waits -> pitch the voice agent; otherwise use judgment "
    "based on their category. Write a short email (under 120 words), "
    "reference one concrete real detail about their business so it doesn't "
    "read as a mass template, and don't invent facts you weren't given. "
    "Professional, low-pressure tone, no hype. Respond with ONLY this JSON, "
    'nothing else: {"pitch": "voice_agent or website", "subject": "...", "body": "..."}'
)

FOOTER = '\n\n—\nGyraq\n{address}\nDon\'t want to hear from us? Just reply "unsubscribe".'


def generate_pitch(biz: Business) -> dict | None:
    user_content = json.dumps(
        {
            "name": biz.name,
            "category": biz.category,
            "rating": biz.rating,
            "review_count": biz.review_count,
            "address": biz.address,
            "has_website": bool(biz.website),
            "reviews": [r.text for r in biz.reviews if r.text],
        }
    )

    payload = json.dumps(
        {
            "model": config.OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
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
