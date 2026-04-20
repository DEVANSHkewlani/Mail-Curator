"""
schemas.py — Pydantic models for The Curator Mail API.

Updated v3.1: Added TestEmailRequest and maintained Python 3.9 compatibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field


# ─── Auth ───────────────────────────────────────────────────────────────────

class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[str] = None


# ─── SMTP ─────────────────────────────────────────────────────────────────────

class SMTPConfig(BaseModel):
    """SMTP credentials & connection details."""
    host: str = Field(..., examples=["smtp.gmail.com"])
    port: int = Field(..., ge=1, le=65535, examples=[587])
    email: EmailStr = Field(..., description="Sender / login address")
    password: str = Field(..., min_length=1)


class SMTPTestResult(BaseModel):
    ok: bool
    message: str
    host: Optional[str] = None
    port: Optional[int] = None


# ─── Contacts ──────────────────────────────────────────────────────────────────

class Contact(BaseModel):
    """
    A single resolved contact row.
    """
    email: EmailStr
    name: Optional[str] = ""
    extra: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_csv_row(cls, row: Dict[str, Any], column_map: "ColumnMap") -> "Contact":
        email_key = column_map.email or "email"
        name_key  = column_map.name  or "name"
        email = str(row.get(email_key, row.get("email", ""))).strip()
        name  = str(row.get(name_key,  row.get("name",  ""))).strip()
        extra = {k: v for k, v in row.items() if k not in (email_key, name_key)}
        return cls(email=email, name=name, extra=extra)


class ColumnMap(BaseModel):
    """Maps semantic field names → actual CSV header strings."""
    email:   str = "email"
    name:    str = "name"
    company: str = ""
    role:    str = ""
    city:    str = ""


class ContactsPayload(BaseModel):
    contacts:   List[Contact]
    column_map: ColumnMap = Field(default_factory=ColumnMap)


class MessageIdLookupRequest(BaseModel):
    """Request to look up prior Message-IDs for reply threading."""
    emails: List[str]


# ─── Compose ──────────────────────────────────────────────────────────────────

class ComposePayload(BaseModel):
    """The email template."""
    from_name:   str = Field("", description="Display name for the sender")
    reply_to:    Optional[EmailStr] = Field(None, description="Reply-To address")
    cc:          Optional[str] = Field(None, description="Comma-separated CC addresses")
    subject:     str = Field(..., min_length=1)
    body_html:   str = Field(..., min_length=1)
    html_mode:   bool = Field(False)
    font_family: Optional[str] = None
    font_size:   Optional[str] = None
    text_color:  Optional[str] = None
    signature:   Optional[str] = None
    signature_enabled: bool = True


# ─── Attachments ──────────────────────────────────────────────────────────────

class AttachmentMeta(BaseModel):
    id:        uuid.UUID
    name:      str
    size:      int
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Send Campaign ────────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    smtp:             SMTPConfig
    compose:          ComposePayload
    contacts:         List[Contact]
    column_map:       ColumnMap = Field(default_factory=ColumnMap)
    attachment_names: List[str] = Field(default_factory=list)
    delay_seconds:    float = Field(3.0, ge=0, le=60)
    campaign_name:    Optional[str] = Field(None)


class TestEmailRequest(BaseModel):
    """Payload for sending a single test email."""
    smtp:    SMTPConfig
    compose: ComposePayload
    to:      EmailStr


class RecipientResult(BaseModel):
    """Outcome for a single recipient."""
    email:      str
    name:       str
    subject:    str
    ok:         bool
    error:      Optional[str] = None
    message_id: Optional[str] = None


class SendProgress(BaseModel):
    total:   int
    sent:    int
    failed:  int
    current: int
    done:    bool = False
    stopped: bool = False
    result:  Optional[RecipientResult] = None


class SendSummary(BaseModel):
    total:    int
    sent:     int
    failed:   int
    failures: List[RecipientResult] = Field(default_factory=list)
    stopped:  bool = False


# ─── Campaign (DB) ────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name:              str
    from_name:         Optional[str] = None
    reply_to:          Optional[str] = None
    cc:                Optional[str] = None
    subject:           str
    body_html:         str
    font_family:       Optional[str] = None
    font_size:         Optional[str] = None
    text_color:        Optional[str] = None
    signature:         Optional[str] = None
    signature_enabled: bool = True


class CampaignResponse(CampaignCreate):
    id:         uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Send History (DB) ────────────────────────────────────────────────────────

class SendResultResponse(BaseModel):
    id:              uuid.UUID
    recipient_email: str
    recipient_name:  Optional[str]
    subject:         Optional[str]
    message_id:      Optional[str]
    ok:              bool
    error:           Optional[str]
    sent_at:         datetime

    class Config:
        from_attributes = True


class SendLogResponse(BaseModel):
    id:            uuid.UUID
    campaign_name: Optional[str]
    started_at:    datetime
    completed_at:  Optional[datetime]
    total:         int
    sent:          int
    failed:        int
    stopped:       bool

    class Config:
        from_attributes = True
