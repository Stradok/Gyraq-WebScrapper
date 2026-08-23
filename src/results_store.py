import json
import os

from . import config


def list_result_files() -> list[dict]:
    if not os.path.isdir(config.RESULTS_DIR):
        return []
    names = sorted((f for f in os.listdir(config.RESULTS_DIR) if f.endswith(".json")), reverse=True)
    out = []
    for name in names:
        path = os.path.join(config.RESULTS_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        out.append(
            {
                "file": name,
                "query": data.get("query"),
                "scraped_at": data.get("scraped_at"),
                "count": data.get("count"),
            }
        )
    return out


def read_result_file(name: str) -> dict | None:
    safe_name = os.path.basename(name)  # guard against path traversal
    path = os.path.join(config.RESULTS_DIR, safe_name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
