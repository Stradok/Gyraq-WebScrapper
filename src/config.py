import os


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


QUERIES_FILE = os.environ.get("QUERIES_FILE", "data/queries.yaml")
RESULTS_DIR = os.environ.get("RESULTS_DIR", "data/results")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
DELAY_BETWEEN_QUERIES_MIN = int(os.environ.get("DELAY_BETWEEN_QUERIES_MIN", "20"))
DELAY_BETWEEN_QUERIES_MAX = int(os.environ.get("DELAY_BETWEEN_QUERIES_MAX", "60"))

DEFAULT_MAX_RESULTS = int(os.environ.get("DEFAULT_MAX_RESULTS", "60"))
REVIEWS_PER_BUSINESS = int(os.environ.get("REVIEWS_PER_BUSINESS", "5"))

HEADLESS = _bool("HEADLESS", True)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "45000"))

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8080"))
