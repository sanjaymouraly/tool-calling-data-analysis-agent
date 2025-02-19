"""HTTP API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #


class DatasetOut(ApiModel):
    id: str
    name: str
    original_filename: str
    file_type: str
    sheet_name: str | None = None
    row_count: int
    column_count: int
    size_bytes: int
    currency: str
    is_demo: bool
    is_approved: bool
    description: str | None = None
    lineage_id: str
    version: int
    created_at: datetime
    updated_at: datetime
    file_hash: str


class ColumnOut(ApiModel):
    name: str
    position: int = 0
    dtype: str = "object"
    inferred_type: str = "string"
    inference_reason: str = ""
    nullable: bool = True
    missing_count: int = 0
    missing_pct: float = 0.0
    unique_count: int | None = None
    sample_values: list[Any] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    currency: str | None = None
    role_hint: str | None = None


class DatasetDetailOut(DatasetOut):
    profile: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)


class SchemaOut(ApiModel):
    dataset_id: str
    dataset_name: str
    row_count: int
    column_count: int
    columns: list[ColumnOut]
    warnings: list[str] = Field(default_factory=list)
    currency: str = "USD"


class PreviewOut(ApiModel):
    dataset_id: str
    rows: list[dict[str, Any]]
    columns: list[str]
    total_rows: int
    limit: int
    offset: int


class QualityOut(ApiModel):
    dataset_id: str
    score: float
    row_count: int
    column_count: int
    missing_values: dict[str, Any] = Field(default_factory=dict)
    duplicates: dict[str, Any] = Field(default_factory=dict)
    outliers: dict[str, Any] = Field(default_factory=dict)
    type_issues: list[Any] = Field(default_factory=list)
    constant_columns: list[str] = Field(default_factory=list)
    issues: list[Any] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UploadOut(ApiModel):
    id: str
    name: str
    row_count: int
    column_count: int
    file_hash: str
    sheet_name: str | None = None
    version: int
    is_demo: bool


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #


class ApprovedJoinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_dataset_id: str = Field(..., max_length=64)
    right_dataset_id: str = Field(..., max_length=64)
    left_key: str = Field(..., max_length=200)
    right_key: str = Field(..., max_length=200)
    notes: str | None = Field(default=None, max_length=500)


class AnalysisRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=3, max_length=2000)
    dataset_ids: list[str] = Field(..., min_length=1, max_length=10)
    provider: str = Field(default="free", max_length=32)
    conversation_id: str | None = Field(default=None, max_length=64)
    approved_joins: list[ApprovedJoinIn] = Field(default_factory=list, max_length=10)
    max_rounds: int | None = Field(default=None, ge=1, le=32)

    @field_validator("dataset_ids")
    @classmethod
    def _unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("dataset_ids must not contain duplicates")
        return value


class AnalysisResponseOut(ApiModel):
    id: str
    conversation_id: str | None = None
    question: str
    answer: str
    status: str
    plan: dict[str, Any]
    tool_trace: list[dict[str, Any]]
    evidence: dict[str, Any]
    how_calculated: dict[str, Any]
    charts: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    clarification: str | None = None
    provider: str
    model: str | None = None
    latency_ms: int
    states: list[str] = Field(default_factory=list)


class HistoryOut(ApiModel):
    id: str
    question: str
    provider: str
    model: str | None = None
    status: str
    latency_ms: int
    created_at: datetime
    dataset_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Settings / providers
# --------------------------------------------------------------------------- #


class ProviderConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., max_length=32)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=128)
    enabled: bool = True
    price_input_per_mtok: float = Field(default=0.0, ge=0.0, le=1000.0)
    price_output_per_mtok: float = Field(default=0.0, ge=0.0, le=1000.0)


class ProviderTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., max_length=32)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=128)


class ProviderStatusOut(ApiModel):
    provider: str
    label: str
    requires_key: bool
    base_url: str
    model: str
    has_key: bool
    masked_key: str | None = None
    key_hint: str | None = None
    supports_native_tools: bool
    supports_model_listing: bool
    notes: str = ""
    source: str = "environment"


class MetricDefinitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = Field(default=None, max_length=64)
    name: str = Field(..., max_length=120)
    label: str = Field(..., max_length=200)
    kpi: str = Field(..., max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    unit: str = Field(default="", max_length=32)
    currency: str = Field(default="USD", max_length=8)
    is_approved: bool = True
    description: str | None = Field(default=None, max_length=1000)


class MetricDefinitionOut(ApiModel):
    id: str
    dataset_id: str | None = None
    name: str
    label: str
    kpi: str
    params: dict[str, Any] = Field(default_factory=dict)
    unit: str = ""
    currency: str = "USD"
    is_approved: bool = True
    description: str | None = None


class ApprovedJoinInOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_dataset_id: str = Field(..., max_length=64)
    right_dataset_id: str = Field(..., max_length=64)
    left_key: str = Field(..., max_length=200)
    right_key: str = Field(..., max_length=200)
    notes: str | None = Field(default=None, max_length=500)


class SavedReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    analysis_id: str | None = Field(default=None, max_length=64)
    dataset_id: str | None = Field(default=None, max_length=64)
    chart: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class SavedReportOut(ApiModel):
    id: str
    title: str
    analysis_id: str | None = None
    dataset_id: str | None = None
    chart: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_at: datetime
