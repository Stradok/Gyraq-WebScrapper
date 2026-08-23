import json
import logging
import urllib.request

from . import config
from .models import Business

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are writing a short, personalized cold outreach email on behalf of "
    "Gyraq (services@gyraq.com), which helps local businesses in four ways: "
    "1) AI VOICE AGENTS - an automated receptionist/customer support line "
    "that answers calls, takes messages, and books appointments 24/7 with no "
    "hold times. 2) WEBSITE - professional website design/building for "
    "businesses with no website or an outdated one. 3) AUTOMATION - "
    "connecting a business's existing tools/workflow so repetitive manual "
    "work (appointment reminders, follow-ups, review requests, scheduling, "
    "data entry between systems) happens automatically instead of by hand. "
    "4) LEAD_GENERATION - finding and delivering new customer leads for "
    "businesses that want to grow their customer base, especially ones with "
    "limited online visibility or reach right now. "
    ""
    "You'll be given data about one specific local business: their Google "
    "review text, review_count, and - when available - search snippets from "
    "Reddit ('reddit_mentions') and other review sites like Yelp "
    "('other_mentions') that came up when searching for this business by "
    "name. "
    ""
    "Decide which ONE of the four fits best: no website or a very basic one "
    "-> website; any source mentioning missed calls, slow replies, being "
    "hard to reach, or long waits -> voice_agent; mentions of manual "
    "scheduling problems, missed follow-ups, no online booking, or generally "
    "repetitive admin overhead -> automation; a low review_count or other "
    "signs the business has limited reach/visibility and would benefit from "
    "more customer volume -> lead_generation; otherwise use judgment based "
    "on their category. Pick exactly one - don't pitch multiple services in "
    "the same email. "
    ""
    "How to use the research: if reddit_mentions or other_mentions contain a "
    "REAL, SPECIFIC complaint or pain point relevant to one of the four "
    "services, cite it directly as concrete evidence (e.g. 'I came across a "
    "Reddit thread where a customer mentioned...') - this is your strongest "
    "possible opening, use it if it's there. Never fabricate a complaint "
    "that isn't in the data, and never twist a positive/neutral mention "
    "(a good review, a simple listing) into a fake complaint - if what you "
    "have is neutral or positive, don't pretend otherwise. If there is no "
    "usable complaint anywhere (Google reviews, reddit_mentions, or "
    "other_mentions all empty or all positive/neutral), skip proof entirely "
    "and instead write a strong, concise pitch grounded in a common, "
    "credible use case for their specific business category (e.g. "
    "'restaurants like yours often lose bookings to after-hours missed "
    "calls') - confident and specific to their category, not a vague "
    "generic template, but don't claim this specific business has that "
    "problem if you have no evidence of it. "
    ""
    "Write a short email (under 130 words) that references at least one "
    "concrete real detail about their business so it doesn't read as a mass "
    "template, and don't invent facts you weren't given. Professional, "
    "low-pressure tone, no hype, and don't stack more than one proof point "
    "- a single strong one beats several. Always sign off as exactly "
    "'The Gyraq Team' - never a placeholder like [Your Name]. Respond with "
    "ONLY this JSON, "
    'nothing else: {"pitch": "voice_agent, website, automation, or '
    'lead_generation", "subject": "...", "body": "..."}'
)

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
