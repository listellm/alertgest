"""SQLAlchemy database models."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class Alert(Base):
    """Alert instances received from AlertManager."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alertname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    namespace: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False)
    annotations: Mapped[dict] = mapped_column(JSONB, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    capture_window_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("capture_windows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationship
    capture_window: Mapped[Optional["CaptureWindow"]] = relationship(back_populates="alerts")

    __table_args__ = (
        Index("idx_alerts_labels", labels, postgresql_using="gin"),
        Index("idx_alerts_received", "received_at"),
    )


class CaptureWindow(Base):
    """Capture window tracking overnight periods."""

    __tablename__ = "capture_windows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    window_start: Mapped[datetime] = mapped_column(nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(nullable=False, index=True)
    digest_generated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    digest_sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)

    # Relationships
    alerts: Mapped[list["Alert"]] = relationship(back_populates="capture_window", cascade="all, delete-orphan")
    digests: Mapped[list["Digest"]] = relationship(back_populates="capture_window", cascade="all, delete-orphan")


class Digest(Base):
    """Generated digest summaries for audit and debugging."""

    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capture_window_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("capture_windows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formatted_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    teams_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # Relationship
    capture_window: Mapped["CaptureWindow"] = relationship(back_populates="digests")
