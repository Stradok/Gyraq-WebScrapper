import csv
import json
import os
import re
from datetime import datetime, timezone

from .models import Business

CSV_FIELDS = [
    "name",
    "category",
    "rating",
    "review_count",
    "price_level",
    "address",
    "phone",
    "website",
    "hours",
    "latitude",
    "longitude",
    "google_maps_url",
    "top_reviews",
]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "query"


def write_results(query: str, businesses: list[Business], results_dir: str) -> tuple[str, str]:
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{slugify(query)}_{timestamp}"

    json_path = os.path.join(results_dir, f"{base}.json")
    csv_path = os.path.join(results_dir, f"{base}.csv")

    payload = {
        "query": query,
        "scraped_at": timestamp,
        "count": len(businesses),
        "results": [b.to_dict() for b in businesses],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for b in businesses:
            row = b.to_dict()
            top_reviews = " | ".join(
                f"{r.get('author') or 'anon'} ({r.get('rating')}): {r.get('text') or ''}".strip()
                for r in row.pop("reviews", [])
                if r.get("text") or r.get("rating")
            )
            row["top_reviews"] = top_reviews
            writer.writerow(row)

    return csv_path, json_path
