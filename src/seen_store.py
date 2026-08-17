import os
import re
import threading

PLACE_ID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")


def extract_place_id(url_or_href: str | None) -> str | None:
    if not url_or_href:
        return None
    m = PLACE_ID_RE.search(url_or_href)
    return m.group(1) if m else url_or_href


class SeenStore:
    """Tracks Google Maps place IDs already captured in a previous run,
    persisted to a plain text file so it survives container restarts."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            self._ids = {line.strip() for line in f if line.strip()}

    def has(self, place_id: str | None) -> bool:
        if not place_id:
            return False
        with self._lock:
            return place_id in self._ids

    def count(self) -> int:
        with self._lock:
            return len(self._ids)

    def add(self, place_id: str | None) -> None:
        if not place_id:
            return
        with self._lock:
            if place_id in self._ids:
                return
            self._ids.add(place_id)
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(place_id + "\n")
