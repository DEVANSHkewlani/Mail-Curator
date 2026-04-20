"""
models.py — SQLAlchemy ORM models for The Curator Mail.

Updated for Multi-User isolation (v3).
Updated v3.1: Python 3.9 compatibility (Optional instead of |).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ─── User ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    campaigns: Mapped[List[Campaign]] = relationship("Campaign", back_populates="user", cascade="all, delete-orphan")
    send_logs: Mapped[List[SendLog]] = relationship("SendLog", back_populates="user", cascade="all, delete-orphan")
    attachments: Mapped[List[Attachment]] = relationship("Attachment", back_populates="user", cascade="all, delete-orphan")


# ─── Campaign ────────────────────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Sender settings
    from_name: Mapped[Optional[str]] = mapped_column(Text)
    reply_to:  Mapped[Optional[str]] = mapped_column(Text)
    cc:        Mapped[Optional[str]] = mapped_column(Text)

    # Content
    subject:   Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)

    # Typography
    font_family: Mapped[Optional[str]] = mapped_column(Text)
    font_size:   Mapped[Optional[str]] = mapped_column(String(20))
    text_color:  Mapped[Optional[str]] = mapped_column(String(20))

    # Signature
    signature:         Mapped[Optional[str]] = mapped_column(Text)
    signature_enabled: Mapped[bool]          = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="campaigns")


# ─── Send Log ─────────────────────────────────────────────────────────────────

class SendLog(Base):
    """One row per campaign dispatch run."""
    __tablename__ = "send_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_name: Mapped[Optional[str]] = mapped_column(Text)
    started_at:    Mapped[datetime]      = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total:   Mapped[int]  = mapped_column(Integer, default=0)
    sent:    Mapped[int]  = mapped_column(Integer, default=0)
    failed:  Mapped[int]  = mapped_column(Integer, default=0)
    stopped: Mapped[bool] = mapped_column(Boolean, default=False)

    results: Mapped[List[SendResult]] = relationship(
        "SendResult", back_populates="log", cascade="all, delete-orphan"
    )
    user: Mapped[User] = relationship("User", back_populates="send_logs")


# ─── Send Result ──────────────────────────────────────────────────────────────

class SendResult(Base):
    """Per-recipient outcome. The message_id column enables reply threading."""
    __tablename__ = "send_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("send_logs.id", ondelete="CASCADE")
    )
    recipient_email: Mapped[str]           = mapped_column(Text, nullable=False)
    recipient_name:  Mapped[Optional[str]] = mapped_column(Text)
    subject:         Mapped[Optional[str]] = mapped_column(Text)

    # RFC 5322 Message-ID — stored for reply threading in follow-up campaigns
    message_id: Mapped[Optional[str]] = mapped_column(Text, index=True)

    ok:    Mapped[bool]           = mapped_column(Boolean, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    log: Mapped[SendLog] = relationship("SendLog", back_populates="results")


# ─── Attachment ───────────────────────────────────────────────────────────────

class Attachment(Base):
    """Metadata for files uploaded by users."""
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename:  Mapped[str] = mapped_column(Text, nullable=False)
    size:      Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="attachments")
