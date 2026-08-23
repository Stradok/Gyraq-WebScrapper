import json
import logging
import os

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import config
from .auth import verify_token
from .drafts_store import get_draft, list_drafts as _list_drafts
from .drafts_store import mark_failed, mark_sent, save_draft
from .jobs import Job, job_store
from .live_view import get_frame
from .mail_settings import masked_mail_settings, save_mail_settings
from .mailer import MailNotConfigured, send_email, test_imap, test_smtp
from .qr import make_qr_png
from .results_store import list_result_files, read_result_file
from .stats import get_stats
from .whatsapp import (
    WhatsAppNotConfigured,
    list_inbox,
    parse_webhook_payload,
    record_incoming,
    test_connection as test_whatsapp_connection,
    verify_webhook_signature,
)
from .whatsapp_settings import (
    get_whatsapp_settings,
    masked_whatsapp_settings,
    save_whatsapp_settings,
)

log = logging.getLogger(__name__)

app = FastAPI(title="Maps Scraper API")

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

# Every route below except /health, the WhatsApp webhook (which has its own
# verify-token / signature protection instead), and the static web UI shell
# requires this app's own token - see src/auth.py. The web UI shell has to
# stay open so the page can load and prompt for the token in the first place.
AUTH_PREFIXES = (
    "/scrape",
    "/jobs",
    "/drafts",
    "/live",
    "/settings",
    "/results",
    "/stats",
    "/whatsapp/inbox",
    "/qr",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(AUTH_PREFIXES):
            if not verify_token(request.headers.get("x-app-token")):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


app.add_middleware(AuthMiddleware)


class ScrapeRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=config.DEFAULT_MAX_RESULTS, ge=1, le=500)


class DraftRequest(BaseModel):
    to: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    business_name: str | None = None
    pitch: str | None = None


class MailSettingsRequest(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    imap_use_ssl: bool | None = None
    from_name: str | None = None
    from_email: str | None = None


class SendDraftsRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class WhatsAppSettingsRequest(BaseModel):
    access_token: str | None = None
    phone_number_id: str | None = None
    waba_id: str | None = None
    verify_token: str | None = None
    app_secret: str | None = None


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


@app.get("/settings/mail")
def get_mail_settings_route() -> dict:
    return masked_mail_settings()


@app.post("/settings/mail")
def update_mail_settings(req: MailSettingsRequest) -> dict:
    values = req.model_dump(exclude_unset=True)
    save_mail_settings(values)
    return masked_mail_settings()


@app.post("/settings/mail/test-smtp")
def test_smtp_route() -> dict:
    try:
        test_smtp()
        return {"ok": True}
    except MailNotConfigured as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/settings/mail/test-imap")
def test_imap_route() -> dict:
    try:
        test_imap()
        return {"ok": True}
    except MailNotConfigured as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/drafts/send")
def send_drafts(req: SendDraftsRequest) -> dict:
    if req.all:
        targets = [d["id"] for d in _list_drafts() if d["status"] == "pending"]
    else:
        targets = req.ids or []

    sent, failed, errors = 0, 0, []
    for draft_id in targets:
        draft = get_draft(draft_id)
        if draft is None:
            continue
        try:
            send_email(draft["to"], draft["subject"], draft["body"])
            mark_sent(draft_id)
            sent += 1
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            mark_failed(draft_id, err)
            failed += 1
            errors.append({"id": draft_id, "to": draft["to"], "error": err})

    return {"sent": sent, "failed": failed, "errors": errors}


@app.get("/results")
def list_results() -> list[dict]:
    return list_result_files()


@app.get("/results/{filename}")
def get_result(filename: str) -> dict:
    data = read_result_file(filename)
    if data is None:
        raise HTTPException(status_code=404, detail="result file not found")
    return data


@app.get("/stats")
def stats() -> dict:
    return get_stats()


@app.get("/settings/whatsapp")
def get_whatsapp_settings_route() -> dict:
    return masked_whatsapp_settings()


@app.post("/settings/whatsapp")
def update_whatsapp_settings(req: WhatsAppSettingsRequest) -> dict:
    values = req.model_dump(exclude_unset=True)
    save_whatsapp_settings(values)
    return masked_whatsapp_settings()


@app.post("/settings/whatsapp/test")
def test_whatsapp_route() -> dict:
    try:
        info = test_whatsapp_connection()
        return {"ok": True, "info": info}
    except WhatsAppNotConfigured as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/whatsapp/inbox")
def whatsapp_inbox() -> list[dict]:
    return list_inbox()


@app.get("/webhooks/whatsapp")
def verify_whatsapp_webhook(request: Request) -> PlainTextResponse:
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")
    expected = get_whatsapp_settings().get("verify_token")
    if mode == "subscribe" and expected and token == expected:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="verification failed")


@app.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request) -> dict:
    raw = await request.body()
    app_secret = get_whatsapp_settings().get("app_secret")
    if app_secret:
        signature = request.headers.get("x-hub-signature-256")
        if not verify_webhook_signature(raw, signature, app_secret):
            raise HTTPException(status_code=403, detail="invalid signature")
    else:
        log.warning("WhatsApp webhook received with no app_secret configured - signature not verified")

    payload = json.loads(raw)
    for msg in parse_webhook_payload(payload):
        record_incoming(msg["from"], msg["text"], payload)
    return {"status": "received"}


@app.get("/qr")
def qr_code(request: Request) -> Response:
    url = request.query_params.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="missing url param")
    return Response(content=make_qr_png(url), media_type="image/png")


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
