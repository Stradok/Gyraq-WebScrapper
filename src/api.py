import os

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .drafts_store import list_drafts as _list_drafts
from .drafts_store import save_draft
from .jobs import Job, job_store
from .live_view import get_frame

app = FastAPI(title="Maps Scraper API")

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=config.DEFAULT_MAX_RESULTS, ge=1, le=500)


class DraftRequest(BaseModel):
    to: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    business_name: str | None = None
    pitch: str | None = None


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


@app.post("/drafts")
def create_draft(req: DraftRequest) -> dict:
    record = save_draft(req.to, req.subject, req.body, req.business_name, req.pitch)
    return {"status": "saved", **record}


@app.get("/drafts")
def list_drafts() -> list[dict]:
    return _list_drafts()


@app.get("/live")
def live_frame() -> Response:
    data, taken_at = get_frame()
    if data is None:
        return Response(status_code=204)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Taken-At": str(taken_at)},
    )


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
