from datetime import datetime, timezone

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "business_name": row["business_name"],
        "to": row["to_email"],
        "subject": row["subject"],
        "body": row["body"],
        "pitch": row["pitch"],
        "status": row["status"],
        "created_at": row["created_at"],
        "sent_at": row["sent_at"],
        "error": row["error"],
    }


def save_draft(
    to: str, subject: str, body: str, business_name: str | None = None, pitch: str | None = None
) -> dict:
    created_at = _now()
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO drafts (business_name, to_email, subject, body, pitch, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (business_name, to, subject, body, pitch, created_at),
        )
        draft_id = cur.lastrowid
    return {
        "id": draft_id,
        "to": to,
        "subject": subject,
        "body": body,
        "business_name": business_name,
        "pitch": pitch,
        "status": "pending",
        "created_at": created_at,
        "sent_at": None,
        "error": None,
    }


def list_drafts() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM drafts ORDER BY created_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_draft(draft_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return _row_to_dict(row) if row else None


def mark_sent(draft_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'sent', sent_at = ?, error = NULL WHERE id = ?",
            (_now(), draft_id),
        )


def mark_failed(draft_id: int, error: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'failed', error = ? WHERE id = ?", (error, draft_id)
        )


def update_draft(
    draft_id: int, to: str | None = None, subject: str | None = None, body: str | None = None
) -> dict | None:
    fields, values = [], []
    if to is not None:
        fields.append("to_email = ?")
        values.append(to)
    if subject is not None:
        fields.append("subject = ?")
        values.append(subject)
    if body is not None:
        fields.append("body = ?")
        values.append(body)
    if not fields:
        return get_draft(draft_id)
    values.append(draft_id)
    with db.connect() as conn:
        conn.execute(f"UPDATE drafts SET {', '.join(fields)} WHERE id = ?", values)
    return get_draft(draft_id)


def delete_draft(draft_id: int) -> bool:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    return cur.rowcount > 0
