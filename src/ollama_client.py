import json
import urllib.request

from . import config


def list_models() -> list[str]:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []
