import json
import queue
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    query: str
    max_results: int
    status: str = "queued"  # queued -> running -> done | error
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    result_count: int | None = None
    results: list[dict] | None = None
    csv_path: str | None = None
    json_path: str | None = None
    error: str | None = None


def _row_to_job(row) -> Job:
    return Job(
        id=row["id"],
        query=row["query"],
        max_results=row["max_results"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_count=row["result_count"],
        results=json.loads(row["results_json"]) if row["results_json"] else None,
        csv_path=row["csv_path"],
        json_path=row["json_path"],
        error=row["error"],
    )


class JobStore:
    def __init__(self):
        self.pending: "queue.Queue[str]" = queue.Queue()
        for job in self.list():
            if job.status == "queued":
                self.pending.put(job.id)

    def create(self, query: str, max_results: int) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], query=query, max_results=max_results)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, query, max_results, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (job.id, job.query, job.max_results, job.status, job.created_at),
            )
        self.pending.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list(self) -> list[Job]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at ASC").fetchall()
        return [_row_to_job(r) for r in rows]

    def update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        columns = []
        values = []
        for key, value in fields.items():
            if key == "results":
                columns.append("results_json = ?")
                values.append(json.dumps(value) if value is not None else None)
            else:
                columns.append(f"{key} = ?")
                values.append(value)
        values.append(job_id)
        with db.connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(columns)} WHERE id = ?", values)


job_store = JobStore()
