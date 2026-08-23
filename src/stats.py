from . import db


def get_stats() -> dict:
    with db.connect() as conn:
        job_row = conn.execute(
            "SELECT COUNT(*) as jobs, COALESCE(SUM(result_count), 0) as businesses "
            "FROM jobs WHERE status = 'done'"
        ).fetchone()
        draft_rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM drafts GROUP BY status"
        ).fetchall()

    draft_counts = {"pending": 0, "sent": 0, "failed": 0}
    for row in draft_rows:
        draft_counts[row["status"]] = row["n"]

    return {
        "jobs_completed": job_row["jobs"],
        "businesses_scraped": job_row["businesses"],
        "drafts_pending": draft_counts["pending"],
        "drafts_sent": draft_counts["sent"],
        "drafts_failed": draft_counts["failed"],
    }
