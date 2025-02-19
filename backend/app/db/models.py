"""SQLAlchemy ORM models.

The schema is intentionally boring: metadata about datasets, the immutable
analysis records that make results reproducible, conversations, saved
reports, provider configuration (secrets never leave this table in clear
text) and an audit trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base with a portable JSON column type."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Dataset(Base, TimestampMixin):
    """A single uploaded file (or workbook sheet) that can be analysed."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    artifact_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage_id: Mapped[str] = mapped_column(String(36), default=_uuid, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def file_hash(self) -> str:
        """Alias of :attr:`source_hash` used by the API layer."""
        return self.source_hash

    __table_args__ = (Index("ix_datasets_hash_sheet", "source_hash", "sheet_name"),)


class DatasetVersion(Base):
    """Immutable snapshot of a dataset version, used for lineage."""

    __tablename__ = "dataset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), default="")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")


class DatasetColumn(Base):
    """Per-column metadata, queryable without re-reading the file."""

    __tablename__ = "dataset_columns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    dtype: Mapped[str] = mapped_column(String(64), default="object")
    inferred_type: Mapped[str] = mapped_column(String(32), default="string")
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    unique_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_pct: Mapped[float] = mapped_column(Float, default=0.0)
    sample_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    role_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_dataset_columns_dataset_pos", "dataset_id", "position"),)


class Conversation(Base, TimestampMixin):
    """A chat thread in the analytics workspace."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), default="New analysis")
    dataset_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(32), default="free")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )


class Message(Base):
    """A single message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class AnalysisRecord(Base):
    """A reproducible analysis: question, plan, tool trace, evidence."""

    __tablename__ = "analysis_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(32), default="free")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_trace_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    how_calculated_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    answer: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class SavedReport(Base):
    """A pinned analysis (optionally with a chart) for the Reports page."""

    __tablename__ = "saved_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_records.id", ondelete="SET NULL"), nullable=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    chart_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ProviderConfig(Base, TimestampMixin):
    """Persisted provider configuration.

    The API key is stored encrypted (Fernet) when ``ENCRYPT_PROVIDER_KEYS`` is
    enabled; only a masked hint is ever returned by the API.
    """

    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_masked: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    price_input_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    price_output_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetricDefinition(Base):
    """User-approved mapping of a business metric onto concrete columns.

    A metric definition removes guesswork: it pins the KPI to explicit
    column names so the agent never has to guess which column is revenue.
    """

    __tablename__ = "metric_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kpi: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unit: Mapped[str] = mapped_column(String(32), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    @property
    def params(self) -> dict:
        """Alias of :attr:`params_json` used by the API layer."""
        return dict(self.params_json or {})


class ApprovedJoin(Base):
    """A user-approved join relationship between two datasets."""

    __tablename__ = "approved_joins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    left_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    right_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    left_key: Mapped[str] = mapped_column(String(200), nullable=False)
    right_key: Mapped[str] = mapped_column(String(200), nullable=False)
    how: Mapped[str] = mapped_column(String(16), default="inner")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class BusinessCalendar(Base):
    """Business calendar configuration (work days, holidays, time zone)."""

    __tablename__ = "business_calendars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    workdays: Mapped[list[Any]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    holidays: Mapped[list[Any]] = mapped_column(JSON, default=list)
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class UsageRecord(Base):
    """Token / cost accounting for provider calls."""

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64), default="plan")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class AuditLog(Base):
    """Audit trail for mutations (upload, delete, provider change, ...)."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
