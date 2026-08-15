from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import config
from .jobs import Job, job_store

app = FastAPI(title="Maps Scraper API")


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=config.DEFAULT_MAX_RESULTS, ge=1, le=500)


def _summary(job: Job) -> dict:
    return {
        "job_id": job.id,
        "query": job.query,
        "max_results": job.max_results,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result_count": job.result_count,
    }


def _full(job: Job) -> dict:
    d = _summary(job)
    d["results"] = job.results
    d["csv_path"] = job.csv_path
    d["json_path"] = job.json_path
    d["error"] = job.error
    return d


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scrape")
def create_scrape(req: ScrapeRequest) -> dict:
    job = job_store.create(req.query, req.max_results)
    return _summary(job)


@app.get("/jobs")
def list_jobs() -> list[dict]:
    return [_summary(j) for j in job_store.list()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _full(job)
