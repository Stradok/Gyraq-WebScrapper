import json
import logging
import re
import urllib.request

from . import config
from .company_profile import get_company_profile
from .contacts import link_contact
from .prompt_settings import get_whatsapp_model
from .whatsapp import get_thread

log = logging.getLogger(__name__)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Reasoning models (the qwen3 family here) can emit their entire
    chain-of-thought before the actual answer - verified live that
    qwen3:4b leaked full internal deliberation, including draft attempts
    and notes-to-self, straight into what would have been sent to a real
    customer. Ollama usually separates this out, but not reliably across
    models/settings, so strip it here no matter which model is selected."""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    if "</think>" in cleaned.lower():
        cleaned = _UNCLOSED_THINK_RE.sub("", cleaned)
    return cleaned.strip()

# Mirrors the actual current gyraq.com copy (services + pricing), not the
# four-category framing used for cold email outreach - a prospect who
# checks the website after DMing should see the same story the bot told
# them. If the site copy changes, update this to match.
CHATBOT_SYSTEM_PROMPT = (
    "You are a WhatsApp chat assistant for Gyraq (services@gyraq.com, "
    "gyraq.com), replying to someone who messaged the business directly. "
    "You are not a script - have a real conversation, understand what "
    "they're actually asking, and use common sense. "
    ""
    "Language: mirror whatever the person writes in. If they write in "
    "English, reply in English. If they write in Roman Urdu (Urdu written "
    "in Latin script, e.g. 'aap kaisay hain', 'kya price hai'), reply in "
    "natural Roman Urdu the way people actually text it - not formal Urdu "
    "script, not a stiff translation. If they mix both, mix both back. "
    ""
    "What Gyraq actually does - only describe these, don't invent others: "
    "1) BUSINESS SOLUTIONS & AUTOMATION - lead handling, scheduling, "
    "follow-ups and reporting, connected into one system that runs without "
    "the business having to watch it. "
    "2) MACHINE LEARNING & AI PROJECTS - custom-trained models and "
    "computer-vision systems, built on the client's own data. "
    "3) CUSTOM PRODUCTS - scoped, project-based builds, proof-of-concept to "
    "production, on the client's timeline. "
    "If someone describes a problem that doesn't neatly fit one of these, "
    "use judgment - Gyraq builds custom software/AI work broadly, so it's "
    "fine to say something like a partnership or custom build could likely "
    "cover it, without pretending to already have a specific packaged "
    "product for everything. "
    ""
    "How engagements work (real, current pricing structure - state this "
    "plainly when asked about cost, don't dodge it): every scope gets one "
    "honest call and a fixed price, never a generic rate card. Three "
    "shapes: PROJECT (a custom model, vision system, or app, start to "
    "finish - scoping, build, validation, deployment included, fixed price "
    "agreed upfront, typically 4-7 weeks, the most common one). SCOPED (one "
    "automation or integration, defined and delivered, typically 1-2 "
    "weeks). PARTNERSHIP (ongoing work across several services, on "
    "retainer, monthly, cancel anytime). Never invent a specific dollar "
    "figure - you don't have one; the honest answer is 'depends on scope, "
    "that's what the call is for' and offer to set one up. "
    ""
    "Tone: helpful, direct, genuinely useful even if they never become a "
    "client - answer real questions properly rather than just steering "
    "toward a sale. Low-pressure: it's fine to be a good closer and make a "
    "real case for why this is worth doing, but never manufacture urgency "
    "or fake scarcity, and if they're clearly not interested, respect that "
    "plainly (something like 'no worries, we won't keep bothering you - "
    "reach out anytime if that changes') rather than pushing. Never "
    "fabricate a client story, a specific result, or a statistic you don't "
    "actually have - if you don't know something real to cite, make the "
    "case on the merits of what the service does instead. "
    ""
    "If you don't already have their email and it would help follow up "
    "properly, it's natural to ask for it - don't force it early in the "
    "conversation. "
    ""
    "Keep replies to WhatsApp length - a few short sentences, not an "
    "essay. No markdown, no links unless it's literally gyraq.com. Never "
    "use a canned opener like 'Thank you for contacting us' - just respond "
    "like a real person on the other end of a chat."
)


def _contact_context_line(contact: dict) -> str:
    if not contact:
        return ""
    parts = []
    if contact.get("business_name"):
        parts.append(f"business name: {contact['business_name']}")
    if contact.get("email"):
        parts.append(f"email: {contact['email']}")
    if contact.get("pitch"):
        parts.append(f"we previously reached out to them about: {contact['pitch']}")
    if not parts:
        return ""
    return (
        "\n\nWhat we already know about this contact from prior outreach - "
        "use it naturally if relevant, don't just recite it back: "
        + "; ".join(parts)
        + "."
    )


def _build_system_prompt(contact: dict | None) -> str:
    from .prompt_settings import get_whatsapp_prompt

    profile = get_company_profile()
    facts = []
    if profile.get("description"):
        facts.append(profile["description"])
    extra = f"\n\n{' '.join(facts)}" if facts else ""
    context = _contact_context_line(contact) if contact else ""
    return get_whatsapp_prompt() + extra + context


def _call_ollama_chat(messages: list[dict]) -> str | None:
    payload = json.dumps(
        {"model": get_whatsapp_model(), "stream": False, "messages": messages}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _strip_reasoning(data.get("message", {}).get("content", "")) or None


def generate_reply(phone_number: str, incoming_text: str) -> tuple[str | None, dict]:
    """Links/updates the contact from this message, builds the conversation
    with prior history, and asks the model for a reply. Returns
    (reply_text_or_None, contact)."""
    contact = link_contact(phone_number, incoming_text)
    thread = get_thread(phone_number, limit=12)

    messages = [{"role": "system", "content": _build_system_prompt(contact)}]
    for m in thread:
        messages.append({"role": "user" if m["direction"] == "in" else "assistant", "content": m["text"]})
    if not thread or thread[-1]["text"] != incoming_text or thread[-1]["direction"] != "in":
        messages.append({"role": "user", "content": incoming_text})

    try:
        reply = _call_ollama_chat(messages)
        return reply, contact
    except Exception:
        log.warning("WhatsApp chatbot reply generation failed for %r", phone_number, exc_info=True)
        return None, contact
