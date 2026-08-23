import json

from . import config, db

SETTINGS_KEY = "prompt"
MODEL_KEY = "ollama_model"

DEFAULT_SYSTEM_PROMPT = (
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
    "Reddit ('reddit_mentions'), other review sites like Yelp "
    "('other_mentions'), and LinkedIn ('linkedin_mentions') that came up "
    "when searching for this business by name. "
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
    "possible opening, use it if it's there. linkedin_mentions is different - "
    "it's rarely a complaint, it's evidence of the team/company itself (staff "
    "profiles, a company page). Use it only as light, factual color (e.g. "
    "confirming the business is a real, active company) and never invent a "
    "complaint from it. Never fabricate a complaint that isn't in the data, "
    "and never twist a positive/neutral mention (a good review, a simple "
    "listing) into a fake complaint - if what you have is neutral or "
    "positive, don't pretend otherwise. If there is no usable complaint "
    "anywhere (Google reviews, reddit_mentions, or other_mentions all empty "
    "or all positive/neutral), skip proof entirely "
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


def get_system_prompt() -> str:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,)
        ).fetchone()
    if row:
        data = json.loads(row["value"])
        prompt = data.get("system_prompt")
        if prompt:
            return prompt
    return DEFAULT_SYSTEM_PROMPT


def save_system_prompt(prompt: str) -> str:
    prompt = prompt.strip() or DEFAULT_SYSTEM_PROMPT
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_KEY, json.dumps({"system_prompt": prompt})),
        )
    return prompt


def reset_system_prompt() -> str:
    with db.connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (SETTINGS_KEY,))
    return DEFAULT_SYSTEM_PROMPT


def get_ollama_model() -> str:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (MODEL_KEY,)
        ).fetchone()
    if row:
        model = json.loads(row["value"]).get("model")
        if model:
            return model
    return config.OLLAMA_MODEL


def save_ollama_model(model: str) -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (MODEL_KEY, json.dumps({"model": model})),
        )
    return model
