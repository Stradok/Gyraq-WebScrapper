import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


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


class JobStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self.pending: "queue.Queue[str]" = queue.Queue()

    def create(self, query: str, max_results: int) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], query=query, max_results=max_results)
        with self._lock:
            self._jobs[job.id] = job
        self.pending.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)


job_store = JobStore()
