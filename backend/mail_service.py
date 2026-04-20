"""
mail_service.py — Core mail-automation engine for The Curator Mail.

Key changes vs original:
  - build_message() now returns the generated Message-ID so it can be stored
    for reply threading in future campaigns.
  - build_message() checks contact.extra["_prev_msg_id"] to set In-Reply-To /
    References headers, enabling email thread continuity.
  - send_one() returns message_id in RecipientResult.
  - CC addresses from compose.cc are propagated to the SMTP envelope.
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import socket
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import AsyncGenerator, Dict, Generator, List, Optional

from .schemas import (
    AttachmentMeta,
    ColumnMap,
    ComposePayload,
    Contact,
    RecipientResult,
    SendProgress,
    SendRequest,
    SendSummary,
    SMTPConfig,
    SMTPTestResult,
)

logger = logging.getLogger("curator_mail.service")

# ─── Constants ────────────────────────────────────────────────────────────────

PLACEHOLDER_RE = re.compile(r"\$(\w+)")

_PORT_SECURITY: Dict[int, str] = {
    25:   "starttls",
    465:  "ssl",
    587:  "starttls",
    2525: "starttls",
}


# ─── 1. Placeholder substitution ──────────────────────────────────────────────

def fill_placeholders(template: str, contact: Contact, column_map: ColumnMap) -> str:
    """
    Replace $name, $email, $company, $role, $city (and any other $key that
    matches a key in contact.extra) with real values from the contact row.
    Unknown placeholders are left as-is.
    """
    subs: Dict[str, str] = {
        "name":    contact.name or "",
        "email":   contact.email,
        "company": str(contact.extra.get(column_map.company or "company", contact.extra.get("company", ""))),
        "role":    str(contact.extra.get(column_map.role    or "role",    contact.extra.get("role",    ""))),
        "city":    str(contact.extra.get(column_map.city    or "city",    contact.extra.get("city",    ""))),
    }
    for k, v in contact.extra.items():
        subs.setdefault(k, str(v))

    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return subs.get(key, m.group(0))

    return PLACEHOLDER_RE.sub(_replace, template)


# ─── 2. MIME message builder ───────────────────────────────────────────────────

def build_message(
    smtp_cfg:         SMTPConfig,
    compose:          ComposePayload,
    contact:          Contact,
    column_map:       ColumnMap,
    attachment_paths: List[Path],
) -> tuple[MIMEMultipart, str, str]:
    """
    Build a complete MIME message for one recipient.

    Returns:
        (msg, message_id, subject) — The assembled MIME object, its RFC 5322
        Message-ID, and the final subject actually sent.
        The message_id should be stored in the DB for future reply threading.
    """
    subject = fill_placeholders(compose.subject,   contact, column_map)
    body    = fill_placeholders(compose.body_html, contact, column_map)

    # Plain-text fallback
    plain = re.sub(r"<[^>]+>", " ", body)
    plain = re.sub(r"\s+",     " ", plain).strip()

    # ── Assemble MIME tree ──────────────────────────────────────────────────
    msg = MIMEMultipart("mixed")

    message_id = make_msgid(domain=smtp_cfg.host)
    prev_msg_id = contact.extra.get("_prev_msg_id")
    prev_subject = str(contact.extra.get("_prev_subject") or "").strip()
    if prev_msg_id:
        thread_subject = prev_subject or subject
        if not thread_subject.lower().startswith("re:"):
            thread_subject = f"Re: {thread_subject}"
        subject = thread_subject

    msg["Message-ID"] = message_id
    msg["Subject"]    = subject
    msg["From"]       = formataddr((compose.from_name or smtp_cfg.email, smtp_cfg.email))
    msg["To"]         = contact.email

    if compose.reply_to:
        msg["Reply-To"] = compose.reply_to

    if compose.cc:
        msg["Cc"] = compose.cc

    # ── Reply threading ─────────────────────────────────────────────────────
    # The API populates contact.extra["_prev_msg_id"] when this user has
    # successfully emailed the same recipient in a prior campaign run.
    if prev_msg_id:
        msg["In-Reply-To"] = prev_msg_id
        msg["References"]  = prev_msg_id
        logger.info("Threading reply for %s -> %s", contact.email, prev_msg_id)

    # multipart/alternative wraps text + html
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain, "plain", "utf-8"))
    alt.attach(MIMEText(body,  "html",  "utf-8"))
    msg.attach(alt)

    # Attachments
    for path in attachment_paths:
        if not path.exists():
            logger.warning("Attachment not found, skipping: %s", path)
            continue
        with path.open("rb") as fh:
            data = fh.read()
        part = MIMEApplication(data, Name=path.name)
        part["Content-Disposition"] = f'attachment; filename="{path.name}"'
        msg.attach(part)

    return msg, message_id, subject


# ─── 3. SMTP connection helper ─────────────────────────────────────────────────

def _open_smtp(cfg: SMTPConfig, timeout: float = 60.0) -> smtplib.SMTP:
    """Open an authenticated SMTP connection (STARTTLS or SSL based on port)."""
    mode = _PORT_SECURITY.get(cfg.port, "starttls")

    if mode == "ssl":
        conn = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout)
    else:
        conn = smtplib.SMTP(cfg.host, cfg.port, timeout=timeout)
        conn.ehlo()
        try:
            conn.starttls()
            conn.ehlo()
        except smtplib.SMTPNotSupportedError:
            logger.info("Server does not support STARTTLS on port %d", cfg.port)

    conn.login(cfg.email, cfg.password)
    return conn


def _close_smtp(conn: Optional[smtplib.SMTP]) -> None:
    if not conn:
        return
    try:
        conn.quit()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _smtp_error_text(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPResponseException):
        detail = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        return f"{exc.smtp_code} {detail}".strip()
    return str(exc) or exc.__class__.__name__


def _is_disconnected_result(result: RecipientResult) -> bool:
    error = (result.error or "").lower()
    return (
        "server not connected" in error
        or "please run connect" in error
        or "connection unexpectedly closed" in error
        or "timed out" in error
    )


def _ensure_smtp_connected(conn: smtplib.SMTP, cfg: SMTPConfig) -> smtplib.SMTP:
    try:
        code, _ = conn.noop()
        if 200 <= code < 400:
            return conn
    except smtplib.SMTPException:
        pass
    except OSError:
        pass

    logger.info("SMTP connection was not ready; reconnecting to %s:%s", cfg.host, cfg.port)
    _close_smtp(conn)
    return _open_smtp(cfg)


# ─── 4. SMTP test ────────────────────────────────────────────────────────────

def test_smtp_connection(cfg: SMTPConfig) -> SMTPTestResult:
    try:
        conn = _open_smtp(cfg, timeout=8.0)
        conn.quit()
        return SMTPTestResult(
            ok=True,
            message=f"Connected to {cfg.host}:{cfg.port} and authenticated successfully.",
            host=cfg.host,
            port=cfg.port,
        )
    except smtplib.SMTPAuthenticationError as e:
        return SMTPTestResult(ok=False, message=f"Authentication failed: {e.smtp_error.decode(errors='replace')}")
    except smtplib.SMTPConnectError as e:
        return SMTPTestResult(ok=False, message=f"Could not connect: {e}")
    except smtplib.SMTPException as e:
        return SMTPTestResult(ok=False, message=f"SMTP error: {e}")
    except (socket.gaierror, socket.timeout) as e:
        return SMTPTestResult(ok=False, message=f"Network error: {e}")
    except Exception as e:
        logger.exception("Unexpected error during SMTP test")
        return SMTPTestResult(ok=False, message=f"Unexpected error: {e}")


# ─── 5. Single email send ────────────────────────────────────────────────────

def send_one(
    conn:             smtplib.SMTP,
    cfg:              SMTPConfig,
    compose:          ComposePayload,
    contact:          Contact,
    column_map:       ColumnMap,
    attachment_paths: List[Path],
) -> RecipientResult:
    """
    Send one email to one contact using an already-open SMTP connection.
    Returns RecipientResult including the generated message_id.
    """
    subject = fill_placeholders(compose.subject, contact, column_map)
    try:
        msg, message_id, subject = build_message(cfg, compose, contact, column_map, attachment_paths)

        # Recipient envelope = To + any CC addresses
        recipients = [contact.email]
        if compose.cc:
            ccs = [c.strip() for c in compose.cc.split(",") if c.strip()]
            recipients.extend(ccs)

        conn.sendmail(cfg.email, recipients, msg.as_string())
        logger.info("Sent → %s (CC: %s) | %s", contact.email, compose.cc or "none", subject)
        return RecipientResult(
            email=contact.email, name=contact.name or "",
            subject=subject, ok=True, message_id=message_id,
        )
    except smtplib.SMTPRecipientsRefused as e:
        reason = "; ".join(f"{r}: {m.decode(errors='replace')}" for r, (_, m) in e.recipients.items())
        logger.warning("Rejected %s: %s", contact.email, reason)
        return RecipientResult(email=contact.email, name=contact.name or "", subject=subject, ok=False, error=reason)
    except smtplib.SMTPDataError as e:
        reason = _smtp_error_text(e)
        logger.warning("SMTP data rejected for %s: %s", contact.email, reason)
        return RecipientResult(email=contact.email, name=contact.name or "", subject=subject, ok=False, error=reason)
    except smtplib.SMTPException as e:
        reason = _smtp_error_text(e)
        logger.warning("SMTPException for %s: %s", contact.email, reason)
        return RecipientResult(email=contact.email, name=contact.name or "", subject=subject, ok=False, error=reason)
    except OSError as e:
        reason = _smtp_error_text(e)
        logger.warning("Network error for %s: %s", contact.email, reason)
        return RecipientResult(email=contact.email, name=contact.name or "", subject=subject, ok=False, error=reason)


# ─── 6. Campaign batch sender ─────────────────────────────────────────────────

def run_campaign_sync(
    request:          SendRequest,
    attachment_paths: List[Path],
    stop_event:       Optional[asyncio.Event] = None,
) -> Generator[SendProgress, None, SendSummary]:
    """
    Synchronous generator that sends emails one-by-one and yields a
    SendProgress after each attempt.
    """
    contacts = request.contacts
    total    = len(contacts)
    sent = failed = 0
    failures: List[RecipientResult] = []
    stopped = False

    logger.info("Campaign starting — %d recipients, %.1fs delay", total, request.delay_seconds)

    try:
        conn = _open_smtp(request.smtp)
    except Exception as e:
        error = f"Cannot open SMTP connection: {_smtp_error_text(e)}"
        logger.error(error)
        failures = [
            RecipientResult(
                email=contact.email,
                name=contact.name or "",
                subject=fill_placeholders(request.compose.subject, contact, request.column_map),
                ok=False,
                error=error,
            )
            for contact in contacts
        ]
        for idx, result in enumerate(failures, start=1):
            yield SendProgress(total=total, sent=0, failed=idx, current=idx, done=(idx == total), result=result)
        return SendSummary(total=total, sent=0, failed=total, failures=[], stopped=False)

    try:
        for idx, contact in enumerate(contacts, start=1):
            if stop_event and stop_event.is_set():
                logger.info("Stop requested at %d/%d", idx - 1, total)
                stopped = True
                break

            try:
                conn = _ensure_smtp_connected(conn, request.smtp)
                result = send_one(conn, request.smtp, request.compose, contact,
                                  request.column_map, attachment_paths)
            except Exception as e:
                result = RecipientResult(
                    email=contact.email,
                    name=contact.name or "",
                    subject=fill_placeholders(request.compose.subject, contact, request.column_map),
                    ok=False,
                    error=f"SMTP connection failed: {_smtp_error_text(e)}",
                )

            if not result.ok and _is_disconnected_result(result):
                logger.info("Retrying %s after SMTP disconnect", contact.email)
                try:
                    _close_smtp(conn)
                    conn = _open_smtp(request.smtp)
                    result = send_one(conn, request.smtp, request.compose, contact,
                                      request.column_map, attachment_paths)
                except Exception as e:
                    error = f"SMTP reconnect failed: {_smtp_error_text(e)}"
                    logger.warning("%s for %s", error, contact.email)
                    result = RecipientResult(
                        email=contact.email,
                        name=contact.name or "",
                        subject=fill_placeholders(request.compose.subject, contact, request.column_map),
                        ok=False,
                        error=error,
                    )

            if result.ok:
                sent += 1
            else:
                failed += 1
                failures.append(result)

            progress = SendProgress(
                total=total, sent=sent, failed=failed,
                current=idx, done=(idx == total), result=result,
            )
            yield progress

            if idx < total and request.delay_seconds > 0:
                time.sleep(request.delay_seconds)

    finally:
        try:
            _close_smtp(conn)
        except Exception:
            pass

    if stopped:
        yield SendProgress(total=total, sent=sent, failed=failed,
                           current=len(contacts), done=True, stopped=True)

    logger.info("Campaign finished — sent=%d failed=%d stopped=%s", sent, failed, stopped)
    return SendSummary(total=total, sent=sent, failed=failed, failures=failures, stopped=stopped)


# ─── 7. Test email ─────────────────────────────────────────────────────────────

def send_test_email(
    cfg:     SMTPConfig,
    compose: ComposePayload,
    to:      str,
) -> RecipientResult:
    """Send a plain test email (no CSV merge, no attachments)."""
    dummy_contact = Contact(email=to, name="Test Recipient")
    dummy_map     = ColumnMap()

    try:
        conn   = _open_smtp(cfg, timeout=60.0)
        result = send_one(conn, cfg, compose, dummy_contact, dummy_map, attachment_paths=[])
        _close_smtp(conn)
        return result
    except Exception as e:
        logger.exception("Test email failed")
        subject = fill_placeholders(compose.subject, dummy_contact, dummy_map)
        return RecipientResult(email=to, name="Test Recipient", subject=subject, ok=False, error=str(e))
