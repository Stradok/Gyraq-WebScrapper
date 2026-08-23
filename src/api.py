import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, job_control
from .auth import get_or_create_token, verify_token
from .company_profile import get_company_profile, save_company_profile
from .contacts import get_contact, list_contacts
from .drafts_store import delete_draft, get_draft, list_drafts as _list_drafts
from .drafts_store import mark_failed, mark_sent, save_draft, update_draft
from .jobs import Job, job_store
from .live_view import get_frame
from .mail_settings import masked_mail_settings, save_mail_settings
from .mailer import MailNotConfigured, send_email, test_imap, test_smtp
from .ollama_client import list_models
from .pairing import consume_pairing_code, create_pairing_code
from .prompt_settings import (
    DEFAULT_SYSTEM_PROMPT,
    get_ollama_model,
    get_system_prompt,
    get_whatsapp_model,
    get_whatsapp_prompt,
    reset_system_prompt,
    reset_whatsapp_prompt,
    save_ollama_model,
    save_system_prompt,
    save_whatsapp_model,
    save_whatsapp_prompt,
)
from .qr import make_qr_png
from .results_store import list_result_files, read_result_file
from .stats import get_stats
from .whatsapp import (
    WhatsAppNotConfigured,
    list_inbox,
    get_thread,
    parse_webhook_payload,
    record_incoming,
    record_outgoing,
    send_text as send_whatsapp_text,
    test_connection as test_whatsapp_connection,
    verify_webhook_signature,
)
from .whatsapp_bot import generate_reply
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
    "/contacts",
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


class DraftUpdateRequest(BaseModel):
    to: str | None = None
    subject: str | None = None
    body: str | None = None


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


class PromptRequest(BaseModel):
    system_prompt: str = Field(..., min_length=1)


class CompanyProfileRequest(BaseModel):
    company_name: str | None = None
    website: str | None = None
    description: str | None = None


class ModelRequest(BaseModel):
    model: str = Field(..., min_length=1)


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


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in ("queued", "running", "paused"):
        return {"ok": False, "detail": f"job is already {job.status}"}
    if job.status == "queued":
        # Never started - nothing for job_control to signal, just mark it.
        job_store.update(
            job_id, status="cancelled", finished_at=datetime.now(timezone.utc).isoformat()
        )
    else:
        # request_cancel() also clears the pause flag, so a paused job's
        # loop wakes up and notices the cancel instead of staying stuck.
        job_control.request_cancel(job_id)
    return {"ok": True}


@app.post("/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "running":
        return {"ok": False, "detail": "job is not running"}
    job_control.request_pause(job_id)
    job_store.update(job_id, status="paused")
    return {"ok": True}


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "paused":
        return {"ok": False, "detail": "job is not paused"}
    job_control.request_resume(job_id)
    job_store.update(job_id, status="running")
    return {"ok": True}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in ("queued", "running", "paused"):
        raise HTTPException(status_code=409, detail="stop the job before deleting it")
    job_store.delete(job_id)
    return {"ok": True}


@app.post("/jobs/clear")
def clear_finished_jobs() -> dict:
    return {"cleared": job_store.clear_finished()}


@app.post("/drafts")
def create_draft(req: DraftRequest) -> dict:
    record = save_draft(req.to, req.subject, req.body, req.business_name, req.pitch)
    return {"status": "saved", **record}


@app.get("/drafts")
def list_drafts() -> list[dict]:
    return _list_drafts()


@app.delete("/drafts/{draft_id}")
def delete_draft_route(draft_id: int) -> dict:
    if get_draft(draft_id) is None:
        raise HTTPException(status_code=404, detail="draft not found")
    delete_draft(draft_id)
    return {"ok": True}


@app.put("/drafts/{draft_id}")
def update_draft_route(draft_id: int, req: DraftUpdateRequest) -> dict:
    draft = get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    if draft["status"] == "sent":
        raise HTTPException(status_code=409, detail="can't edit an already-sent email")
    return update_draft(draft_id, to=req.to, subject=req.subject, body=req.body)


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
            if draft.get("channel") == "whatsapp":
                # Only works if this contact has messaged us within the
                # last 24h (a WhatsApp platform rule) - cold-starting a
                # conversation needs a Meta-approved template, which isn't
                # configured. That's a real, expected failure mode here,
                # not a bug - Meta's own error message explains why.
                send_whatsapp_text(draft["to"], draft["body"])
            else:
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


@app.get("/settings/prompt")
def get_prompt_route() -> dict:
    return {
        "system_prompt": get_system_prompt(),
        "default_prompt": DEFAULT_SYSTEM_PROMPT,
        "model": get_ollama_model(),
        "whatsapp_model": get_whatsapp_model(),
        "available_models": list_models(),
    }


@app.post("/settings/prompt")
def update_prompt_route(req: PromptRequest) -> dict:
    return {"system_prompt": save_system_prompt(req.system_prompt)}


@app.post("/settings/prompt/reset")
def reset_prompt_route() -> dict:
    return {"system_prompt": reset_system_prompt()}


@app.post("/settings/prompt/model")
def update_model_route(req: ModelRequest) -> dict:
    return {"model": save_ollama_model(req.model)}


@app.post("/settings/prompt/whatsapp-model")
def update_whatsapp_model_route(req: ModelRequest) -> dict:
    return {"whatsapp_model": save_whatsapp_model(req.model)}


@app.get("/settings/chatbot")
def get_chatbot_route() -> dict:
    from .whatsapp_bot import CHATBOT_SYSTEM_PROMPT

    return {
        "system_prompt": get_whatsapp_prompt(),
        "default_prompt": CHATBOT_SYSTEM_PROMPT,
        "model": get_whatsapp_model(),
        "available_models": list_models(),
    }


@app.post("/settings/chatbot")
def update_chatbot_route(req: PromptRequest) -> dict:
    return {"system_prompt": save_whatsapp_prompt(req.system_prompt)}


@app.post("/settings/chatbot/reset")
def reset_chatbot_route() -> dict:
    return {"system_prompt": reset_whatsapp_prompt()}


class ChatbotTestRequest(BaseModel):
    message: str = Field(..., min_length=1)
    phone_number: str = "test-preview"


@app.post("/settings/chatbot/test")
def test_chatbot_route(req: ChatbotTestRequest) -> dict:
    """Preview what the bot would reply, without sending anything or
    touching the real contact record."""
    import time

    from .whatsapp_bot import _build_system_prompt, _call_ollama_chat

    started = time.monotonic()
    try:
        messages = [
            {"role": "system", "content": _build_system_prompt(None)},
            {"role": "user", "content": req.message},
        ]
        reply = _call_ollama_chat(messages)
        return {
            "ok": True,
            "reply": reply,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "model": get_whatsapp_model(),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


@app.get("/settings/company")
def get_company_route() -> dict:
    return get_company_profile()


@app.post("/settings/company")
def update_company_route(req: CompanyProfileRequest) -> dict:
    values = req.model_dump(exclude_unset=True)
    return save_company_profile(values)


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


@app.get("/contacts")
def contacts_route(request: Request) -> list[dict]:
    return list_contacts(request.query_params.get("q"))


@app.get("/contacts/{phone_number}")
def contact_detail_route(phone_number: str) -> dict:
    contact = get_contact(phone_number)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return {**contact, "thread": get_thread(phone_number, limit=50)}


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
        _auto_reply(msg["from"], msg["text"])
    return {"status": "received"}


def _auto_reply(from_number: str, text: str) -> None:
    """Replying to an inbound DM is a normal, fully-supported use of the
    WhatsApp API (unlike cold-starting a conversation, see whatsapp.
    send_text) - no template required. Never lets a reply/send failure
    break webhook processing; the reply (or failure) is always recorded
    so it shows up in the contact's thread either way."""
    reply, _contact, elapsed_ms = generate_reply(from_number, text)
    if not reply:
        return
    try:
        send_whatsapp_text(from_number, reply)
        record_outgoing(from_number, reply, "sent", duration_ms=elapsed_ms)
    except Exception as e:
        record_outgoing(
            from_number, reply, "failed", f"{type(e).__name__}: {e}", duration_ms=elapsed_ms
        )
        log.warning("Failed to send WhatsApp auto-reply to %r", from_number, exc_info=True)


@app.get("/qr")
def qr_code(request: Request) -> Response:
    url = request.query_params.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="missing url param")
    return Response(content=make_qr_png(url), media_type="image/png")


@app.post("/settings/pairing/new")
def new_pairing_code() -> dict:
    """Only an already-authenticated device can mint one of these -
    that's what makes handing it to a new device (via QR) safe."""
    return {"code": create_pairing_code(), "ttl_seconds": 600}


@app.get("/pair/{code}")
def exchange_pairing_code(code: str) -> dict:
    """Deliberately public: the phone scanning the QR hasn't signed in
    yet. Security comes from the code being random, single-use, and
    expiring in 10 minutes - not from an auth header."""
    if not consume_pairing_code(code):
        raise HTTPException(status_code=403, detail="invalid or expired pairing code")
    return {"token": get_or_create_token()}


# Mounted last so it never shadows the API routes above.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
