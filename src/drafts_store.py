import json
import os
from datetime import datetime, timezone

from . import config


def save_draft(
    to: str, subject: str, body: str, business_name: str | None = None, pitch: str | None = None
) -> dict:
    record = {
        "to": to,
        "subject": subject,
        "body": body,
        "business_name": business_name,
        "pitch": pitch,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(config.DRAFTS_FILE) or ".", exist_ok=True)
    with open(config.DRAFTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_drafts() -> list[dict]:
    if not os.path.exists(config.DRAFTS_FILE):
        return []
    records = []
    with open(config.DRAFTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
