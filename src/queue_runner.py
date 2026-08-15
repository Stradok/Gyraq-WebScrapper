import logging
import os
from datetime import datetime, timezone

import yaml

from . import config
from .exporter import write_results
from .maps_scraper import MapsScraper

log = logging.getLogger(__name__)


def _load_queue(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    if not isinstance(data, list):
        log.error("%s must contain a YAML list of query entries", path)
        return []
    return data


def _save_queue(path: str, entries: list[dict]) -> None:
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(entries, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp_path, path)


def _next_pending(entries: list[dict]) -> dict | None:
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("query"):
            continue
        if entry.get("status") in (None, "pending"):
            return entry
    return None


def run_forever() -> None:
    scraper = MapsScraper(headless=config.HEADLESS)
    scraper.start()
    log.info("Browser started. Watching %s for pending queries.", config.QUERIES_FILE)

    try:
        while True:
            entries = _load_queue(config.QUERIES_FILE)
            entry = _next_pending(entries)

            if entry is None:
                log.debug("No pending queries. Sleeping %ss.", config.POLL_INTERVAL_SECONDS)
                _sleep(config.POLL_INTERVAL_SECONDS)
                continue

            query = entry["query"]
            max_results = int(entry.get("max_results") or config.DEFAULT_MAX_RESULTS)

            entry["status"] = "running"
            entry["started_at"] = _now()
            _save_queue(config.QUERIES_FILE, entries)

            log.info("Starting query %r (max_results=%d)", query, max_results)
            try:
                businesses = scraper.search(query, max_results)
                csv_path, json_path = write_results(query, businesses, config.RESULTS_DIR)
                entry["status"] = "done"
                entry["result_count"] = len(businesses)
                entry["csv_path"] = csv_path
                entry["json_path"] = json_path
                log.info("Finished query %r: %d results -> %s", query, len(businesses), csv_path)
            except Exception:
                log.exception("Query %r failed", query)
                entry["status"] = "error"
            finally:
                entry["finished_at"] = _now()
                entries = _load_queue(config.QUERIES_FILE)
                for e in entries:
                    if e.get("query") == query and e.get("status") == "running":
                        e.update(entry)
                _save_queue(config.QUERIES_FILE, entries)

            _sleep_between_queries()
    finally:
        scraper.stop()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sleep(seconds: int) -> None:
    import time

    time.sleep(seconds)


def _sleep_between_queries() -> None:
    import random
    import time

    delay = random.uniform(config.DELAY_BETWEEN_QUERIES_MIN, config.DELAY_BETWEEN_QUERIES_MAX)
    log.info("Sleeping %.0fs before next query.", delay)
    time.sleep(delay)
