"""
main.py — FastAPI application for The Curator Mail backend.

Routes:
  POST /auth/signup             — Register a new account
  POST /auth/login              — Authenticate and get JWT token
  POST /smtp/test               — Test SMTP credentials
  POST /send/test-email         — Send a one-off test email
  POST /send/start              — Start campaign → returns job_id
  GET  /send/stream/{id}        — SSE stream of campaign progress
  POST /send/stop/{id}          — Stop a running campaign
  POST /attachments/upload      — Upload attachment file (identifies user)
  GET  /attachments/{filename}  — Serve an uploaded file (scoped to user)
  DELETE /attachments/{filename}

  POST   /campaigns             — Save/Auto-save a campaign template
  GET    /campaigns             — List user's saved campaigns
  GET    /campaigns/{id}        — Load specific campaign
  DELETE /campaigns/{id}

  POST /contacts/lookup-message-ids — Get user's prior Message-IDs for threading
  GET  /send-history            — List user's send runs
  GET  /send-history/{id}/results — Per-recipient results for a run
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import (
    Depends, FastAPI, File, HTTPException,
    Query, UploadFile, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from .database import AsyncSessionLocal, get_db, init_db
from .mail_service import run_campaign_sync, send_test_email, test_smtp_connection
from .models import User, Campaign, SendLog, SendResult, Attachment
from .schemas import (
    AttachmentMeta,
    CampaignCreate,
    CampaignResponse,
    MessageIdLookupRequest,
    RecipientResult,
    SendLogResponse,
    SendProgress,
    SendRequest,
    SendResultResponse,
    SendSummary,
    SMTPConfig,
    SMTPTestResult,
    TestEmailRequest,
    UserSignup,
    Token,
)
from .auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user_id,
    decode_user_id_from_token,
)

# ─── Setup ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("curator_mail.api")

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="The Curator Mail API",
    description="Backend for The Curator Mail — multi-user bulk email suite.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory running jobs (stores job info + user_id for tracking)
_jobs: Dict[str, Dict] = {}


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_user_attachment_paths(user_id: str, filenames: List[str]) -> List[Path]:
    """Resolve attachment names inside the current user's upload folder."""
    paths: List[Path] = []
    user_dir = (UPLOAD_DIR / user_id).resolve()
    shared_dir = UPLOAD_DIR.resolve()

    for filename in filenames:
        target = (user_dir / filename).resolve()
        if _is_relative_to(target, user_dir) and target.exists():
            paths.append(target)
            continue

        # Backward compatibility for files that predate user-scoped uploads.
        shared_target = (UPLOAD_DIR / filename).resolve()
        if _is_relative_to(shared_target, shared_dir) and shared_target.exists():
            paths.append(shared_target)

    return paths


async def _with_reply_threading(
    db: AsyncSession,
    req: SendRequest,
    user_id: str,
) -> SendRequest:
    """
    Attach the latest prior Message-ID for each recipient sent by this user.
    This keeps reply threading server-side and scoped to the logged-in account.
    """
    normalized_emails = {
        _normalize_email(str(contact.email))
        for contact in req.contacts
        if contact.email
    }
    if not normalized_emails:
        return req

    result = await db.execute(
        select(
            func.lower(SendResult.recipient_email).label("recipient_email"),
            SendResult.message_id,
            SendResult.subject,
        )
        .join(SendLog)
        .where(SendLog.user_id == uuid.UUID(user_id))
        .where(func.lower(SendResult.recipient_email).in_(list(normalized_emails)))
        .where(SendResult.ok == True)
        .where(SendResult.message_id.isnot(None))
        .order_by(SendResult.sent_at.desc())
    )

    latest_by_email: Dict[str, Dict[str, Optional[str]]] = {}
    for email, message_id, subject in result.all():
        if email not in latest_by_email and message_id:
            latest_by_email[email] = {
                "message_id": message_id,
                "subject": subject,
            }

    if not latest_by_email:
        return req

    contacts = []
    for contact in req.contacts:
        previous = latest_by_email.get(_normalize_email(str(contact.email)))
        if not previous:
            contacts.append(contact)
            continue
        extra = dict(contact.extra or {})
        extra["_prev_msg_id"] = previous["message_id"]
        if previous.get("subject"):
            extra["_prev_subject"] = previous["subject"]
        contacts.append(contact.model_copy(update={"extra": extra}))

    return req.model_copy(update={"contacts": contacts})


# ─── Lifecycle ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    """Create all DB tables on startup."""
    await init_db()
    logger.info("Database tables initialised for Multi-User v3.")


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/signup", response_model=Token, tags=["Auth"])
async def signup(body: UserSignup, db: AsyncSession = Depends(get_db)):
    """Create a new user account and return an access token."""
    try:
        new_user = User(
            email=body.email,
            hashed_password=get_password_hash(body.password)
        )
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        access_token = create_access_token(data={"sub": str(new_user.id)})
        return {"access_token": access_token, "token_type": "bearer"}
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")


@app.post("/auth/login", response_model=Token, tags=["Auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Authenticate user and return access token."""
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


# ─── SMTP ─────────────────────────────────────────────────────────────────────

@app.post("/smtp/test", response_model=SMTPTestResult, tags=["SMTP"])
async def smtp_test(cfg: SMTPConfig, user_id: str = Depends(get_current_user_id)) -> SMTPTestResult:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, test_smtp_connection, cfg)


# ─── Test Email ───────────────────────────────────────────────────────────────

@app.post("/send/test-email", response_model=RecipientResult, tags=["Send"])
async def api_send_test_email(req: TestEmailRequest, user_id: str = Depends(get_current_user_id)) -> RecipientResult:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, send_test_email, req.smtp, req.compose, req.to)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error)
    return result


# ─── Campaign Start (SSE) ─────────────────────────────────────────────────────

@app.post("/send/start", tags=["Send"])
async def api_send_start(req: SendRequest, user_id: str = Depends(get_current_user_id)) -> Dict:
    """Start campaign in background. Isolated to current user."""
    job_id   = str(uuid.uuid4())
    stop_evt = asyncio.Event()
    queue: asyncio.Queue[Optional[SendProgress]] = asyncio.Queue()

    # Create the initial send log record linked to user and enrich contacts
    # with this user's previous Message-IDs for reply threading.
    async with AsyncSessionLocal() as db:
        req = await _with_reply_threading(db, req, user_id)
        log = SendLog(
            user_id=uuid.UUID(user_id),
            campaign_name=req.campaign_name or req.compose.subject[:80],
            total=len(req.contacts),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        log_id = log.id

    async def _producer() -> None:
        attachment_paths = _safe_user_attachment_paths(user_id, req.attachment_names)
        loop = asyncio.get_event_loop()

        def _run() -> None:
            gen = run_campaign_sync(req, attachment_paths, stop_evt)
            try:
                while True:
                    progress = next(gen)
                    loop.call_soon_threadsafe(queue.put_nowait, progress)
                    if progress.done:
                        break
            except StopIteration:
                pass
            loop.call_soon_threadsafe(queue.put_nowait, None)

        await loop.run_in_executor(None, _run)

    task = asyncio.create_task(_producer())
    _jobs[job_id] = {
        "stop_event": stop_evt, 
        "queue": queue, 
        "task": task, 
        "log_id": str(log_id),
        "user_id": user_id
    }
    logger.info("Campaign job started for user %s: %s", user_id, job_id)
    return {"job_id": job_id}


@app.get("/send/stream/{job_id}", tags=["Send"])
async def api_send_stream(
    job_id: str,
    token: str = Query(..., description="Bearer token for EventSource authentication"),
):
    """SSE stream — only accessible if the user owns the job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job   = _jobs[job_id]
    user_id = decode_user_id_from_token(token)
    if job["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = job["queue"]
    log_id = job.get("log_id")

    collected: list[RecipientResult] = []
    persisted = False

    async def _event_generator():
        nonlocal persisted
        try:
            while True:
                progress: Optional[SendProgress] = await asyncio.wait_for(queue.get(), timeout=120)
                if progress is None:
                    if log_id and not persisted:
                        await _persist_results(log_id, collected)
                        persisted = True
                    yield 'data: {"done": true}\n\n'
                    break
                if progress.done and not progress.result:
                    if log_id and not persisted:
                        await _persist_results(
                            log_id,
                            collected,
                            stopped=progress.stopped,
                            sent_count=progress.sent,
                            failed_count=progress.failed,
                        )
                        persisted = True
                    yield (
                        f'data: {{"done": true, "stopped": {str(progress.stopped).lower()}, '
                        f'"current": {progress.current}, "sent": {progress.sent}, '
                        f'"failed": {progress.failed}, "total": {progress.total}}}\n\n'
                    )
                    break
                if progress.result:
                    collected.append(progress.result)
                yield f"data: {progress.model_dump_json()}\n\n"
                if progress.done:
                    if log_id and not persisted:
                        await _persist_results(
                            log_id,
                            collected,
                            stopped=progress.stopped,
                            sent_count=progress.sent,
                            failed_count=progress.failed,
                        )
                        persisted = True
                    yield (
                        f'data: {{"done": true, "stopped": {str(progress.stopped).lower()}, '
                        f'"current": {progress.current}, "sent": {progress.sent}, '
                        f'"failed": {progress.failed}, "total": {progress.total}}}\n\n'
                    )
                    break
        except asyncio.TimeoutError:
            yield 'data: {"error": "timeout"}\n\n'
        finally:
            _jobs.pop(job_id, None)

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


async def _persist_results(
    log_id: str,
    results: list[RecipientResult],
    stopped: bool = False,
    sent_count: Optional[int] = None,
    failed_count: Optional[int] = None,
) -> None:
    async with AsyncSessionLocal() as db:
        sent = sent_count if sent_count is not None else sum(1 for r in results if r.ok)
        failed = failed_count if failed_count is not None else sum(1 for r in results if not r.ok)

        await db.execute(
            update(SendLog)
            .where(SendLog.id == uuid.UUID(log_id))
            .values(
                completed_at=datetime.now(timezone.utc),
                sent=sent,
                failed=failed,
                stopped=stopped,
            )
        )
        for r in results:
            db.add(SendResult(
                log_id=uuid.UUID(log_id),
                recipient_email=r.email,
                recipient_name=r.name,
                subject=r.subject,
                message_id=r.message_id,
                ok=r.ok,
                error=r.error,
            ))
        await db.commit()


@app.post("/send/stop/{job_id}", tags=["Send"])
async def api_send_stop(job_id: str, user_id: str = Depends(get_current_user_id)) -> Dict:
    if job_id not in _jobs or _jobs[job_id]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    _jobs[job_id]["stop_event"].set()
    return {"status": "stop_requested", "job_id": job_id}


# ─── Attachments ──────────────────────────────────────────────────────────────

@app.post("/attachments/upload", response_model=AttachmentMeta, status_code=201, tags=["Attachments"])
async def api_upload_attachment(
    file: UploadFile = File(...), 
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
) -> AttachmentMeta:
    # Save file to a user-specific folder
    user_upload_dir = UPLOAD_DIR / user_id
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    
    dest = (user_upload_dir / file.filename).resolve()
    if not _is_relative_to(dest, user_upload_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 64):
            out.write(chunk)
            size += len(chunk)
            
    # Record metadata in DB
    att = Attachment(
        user_id=uuid.UUID(user_id),
        filename=file.filename,
        size=size,
        mime_type=file.content_type or "application/octet-stream"
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    
    return AttachmentMeta(
        id=att.id, 
        name=att.filename, 
        size=att.size, 
        mime_type=att.mime_type, 
        created_at=att.created_at
    )


@app.get("/attachments", response_model=List[AttachmentMeta], tags=["Attachments"])
async def list_attachments(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Attachment).where(Attachment.user_id == uuid.UUID(user_id)))
    return list(result.scalars().all())


@app.get("/attachments/{filename}", tags=["Attachments"])
async def api_serve_attachment(filename: str, user_id: str = Depends(get_current_user_id)):
    """Serve files from the user's specific directory."""
    target = (UPLOAD_DIR / user_id / filename).resolve()
    user_dir = (UPLOAD_DIR / user_id).resolve()
    
    if not _is_relative_to(target, user_dir):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists():
        # Fallback to shared folder for backward compatibility or shared assets if needed
        target = (UPLOAD_DIR / filename).resolve()
        if not target.exists() or not _is_relative_to(target, UPLOAD_DIR.resolve()):
            raise HTTPException(status_code=404, detail="File not found")
            
    return FileResponse(target)


@app.delete("/attachments/{filename}", tags=["Attachments"])
async def api_delete_attachment(filename: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> Dict:
    result = await db.execute(
        select(Attachment).where(and_(Attachment.user_id == uuid.UUID(user_id), Attachment.filename == filename))
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
        
    target = (UPLOAD_DIR / user_id / filename).resolve()
    user_dir = (UPLOAD_DIR / user_id).resolve()
    if not _is_relative_to(target, user_dir):
        raise HTTPException(status_code=403, detail="Forbidden")
    if target.exists():
        target.unlink()
        
    await db.delete(att)
    await db.commit()
    return {"deleted": filename}


# ─── Campaigns (DB) ───────────────────────────────────────────────────────────

@app.post("/campaigns", response_model=CampaignResponse, status_code=201, tags=["Campaigns"])
async def create_campaign(
    body: CampaignCreate, 
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
) -> Campaign:
    # Check if a campaign with this name already exists for this user (for auto-save/overwrite logic)
    result = await db.execute(
        select(Campaign).where(and_(Campaign.user_id == uuid.UUID(user_id), Campaign.name == body.name))
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Update existing (Auto-save mode)
        for key, value in body.model_dump().items():
            setattr(existing, key, value)
        await db.commit()
        await db.refresh(existing)
        return existing
    
    # Create new
    row = Campaign(user_id=uuid.UUID(user_id), **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@app.get("/campaigns", response_model=List[CampaignResponse], tags=["Campaigns"])
async def list_campaigns(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> list[Campaign]:
    result = await db.execute(
        select(Campaign)
        .where(Campaign.user_id == uuid.UUID(user_id))
        .order_by(Campaign.updated_at.desc())
    )
    return list(result.scalars().all())


@app.get("/campaigns/{campaign_id}", response_model=CampaignResponse, tags=["Campaigns"])
async def get_campaign(campaign_id: uuid.UUID, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> Campaign:
    result = await db.execute(
        select(Campaign).where(and_(Campaign.id == campaign_id, Campaign.user_id == uuid.UUID(user_id)))
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return row


@app.delete("/campaigns/{campaign_id}", tags=["Campaigns"])
async def delete_campaign(campaign_id: uuid.UUID, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> Dict:
    result = await db.execute(
        select(Campaign).where(and_(Campaign.id == campaign_id, Campaign.user_id == uuid.UUID(user_id)))
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": str(campaign_id)}


# ─── Reply Threading ──────────────────────────────────────────────────────────

@app.post("/contacts/lookup-message-ids", tags=["Contacts"])
async def lookup_message_ids(
    body: MessageIdLookupRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """
    Look up Message-IDs specifically from THIS user's previous sends.
    Enables true per-user reply threading consistency.
    """
    if not body.emails:
        return {}

    normalized_to_original = {
        _normalize_email(email): email
        for email in body.emails
        if email and email.strip()
    }
    if not normalized_to_original:
        return {}

    result = await db.execute(
        select(func.lower(SendResult.recipient_email), SendResult.message_id)
        .join(SendLog)
        .where(SendLog.user_id == uuid.UUID(user_id))
        .where(func.lower(SendResult.recipient_email).in_(list(normalized_to_original.keys())))
        .where(SendResult.ok == True)
        .where(SendResult.message_id.isnot(None))
        .order_by(SendResult.sent_at.desc())
    )
    rows = result.all()

    seen: Dict[str, str] = {}
    for email, msg_id in rows:
        original_email = normalized_to_original.get(email, email)
        if original_email not in seen and msg_id:
            seen[original_email] = msg_id
    return seen


# ─── Send History ─────────────────────────────────────────────────────────────

@app.get("/send-history", response_model=List[SendLogResponse], tags=["History"])
async def get_send_history(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> list[SendLog]:
    result = await db.execute(
        select(SendLog)
        .where(SendLog.user_id == uuid.UUID(user_id))
        .order_by(SendLog.started_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())


@app.get("/send-history/{log_id}/results", response_model=List[SendResultResponse], tags=["History"])
async def get_send_results(log_id: uuid.UUID, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> list[SendResult]:
    # Verify ownership of the log first
    log_check = await db.execute(
        select(SendLog).where(and_(SendLog.id == log_id, SendLog.user_id == uuid.UUID(user_id)))
    )
    if not log_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Log not found")

    result = await db.execute(
        select(SendResult)
        .where(SendResult.log_id == log_id)
        .order_by(SendResult.sent_at)
    )
    return list(result.scalars().all())


# ─── Static files & Frontend ──────────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/", tags=["UI"])
async def root():
    # Redirect to login if needed, though usually handled by frontend app.js
    return FileResponse(FRONTEND_DIR / "compose.html")

@app.get("/login", tags=["UI"])
async def login_page():
    return FileResponse(FRONTEND_DIR / "login.html")

@app.get("/signup", tags=["UI"])
async def signup_page():
    return FileResponse(FRONTEND_DIR / "signup.html")


# Must be last — don't shadow API routes
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
