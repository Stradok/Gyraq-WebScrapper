import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

_lock = threading.Lock()
_initialized = False


@contextmanager
def connect():
    global _initialized
    os.makedirs(os.path.dirname(config.DB_FILE) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    if not _initialized:
        _init_schema(conn)
        _initialized = True
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    with _lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                max_results INTEGER,
                status TEXT,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                result_count INTEGER,
                csv_path TEXT,
                json_path TEXT,
                error TEXT,
                results_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_name TEXT,
                to_email TEXT,
                subject TEXT,
                body TEXT,
                pitch TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                sent_at TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_number TEXT,
                text TEXT,
                raw_json TEXT,
                received_at TEXT
            )
            """
        )
        # Any job still marked "running" from a previous process (e.g. the
        # container was restarted mid-scrape) is orphaned - it will never
        # get its status updated, so mark it as errored instead of stuck.
        conn.execute(
            "UPDATE jobs SET status = 'error', error = 'interrupted by restart' "
            "WHERE status = 'running'"
        )
        conn.commit()
