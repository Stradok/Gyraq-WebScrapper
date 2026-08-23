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
            os.chmod(config.DB_FILE, 0o600)  # owner-only: holds mail/WhatsApp credentials
        except Exception:
            pass
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
                error TEXT,
                channel TEXT DEFAULT 'email'
            )
            """
        )
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(drafts)")}
        if "channel" not in existing_cols:
            conn.execute("ALTER TABLE drafts ADD COLUMN channel TEXT DEFAULT 'email'")
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT,
                text TEXT,
                status TEXT,
                error TEXT,
                created_at TEXT,
                duration_ms INTEGER
            )
            """
        )
        outbox_cols = {row["name"] for row in conn.execute("PRAGMA table_info(whatsapp_outbox)")}
        if "duration_ms" not in outbox_cols:
            conn.execute("ALTER TABLE whatsapp_outbox ADD COLUMN duration_ms INTEGER")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                phone_number TEXT PRIMARY KEY,
                email TEXT,
                business_name TEXT,
                pitch TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                bot_enabled INTEGER DEFAULT 1
            )
            """
        )
        contact_cols = {row["name"] for row in conn.execute("PRAGMA table_info(contacts)")}
        if "bot_enabled" not in contact_cols:
            conn.execute("ALTER TABLE contacts ADD COLUMN bot_enabled INTEGER DEFAULT 1")
        # Any job still marked "running" or "paused" from a previous process
        # (e.g. the container was restarted mid-scrape, or while paused) is
        # orphaned - its in-memory pause/cancel controls are gone with the
        # old process, so it will never resume or get its status updated.
        # Mark it errored instead of leaving it stuck.
        conn.execute(
            "UPDATE jobs SET status = 'error', error = 'interrupted by restart' "
            "WHERE status IN ('running', 'paused')"
        )
        conn.commit()
