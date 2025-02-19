"""Typed input models for the restricted tool library.

Every tool declares a Pydantic model with ``extra="forbid"``.  That single
setting is a hard security boundary: the model cannot smuggle an unknown
field (such as ``sql``, ``code`` or ``path``) into a tool call, because
validation fails before the handler ever runs.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #


class StrictModel(BaseModel):
    """Base class for all tool inputs: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FilterOp(str, Enum):
    eq = "eq"
    neq = "neq"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    between = "between"
    in_ = "in"
    contains = "contains"
    starts_with = "startswith"
    is_null = "is_null"
    not_null = "not_null"


class Aggregation(str, Enum):
    sum = "sum"
    mean = "mean"
    median = "median"
    min = "min"
    max = "max"
    row_count = "count"
    count_distinct = "count_distinct"
    std = "std"
    var = "var"
    n_unique = "n_unique"
    first = "first"
    last = "last"


class SortDir(str, Enum):
    asc = "asc"
    desc = "desc"


class ChartType(str, Enum):
    bar = "bar"
    column = "column"
    line = "line"
    area = "area"
    pie = "pie"
    donut = "donut"
    scatter = "scatter"
    histogram = "histogram"
    heatmap = "heatmap"
    table = "table"


class FilterSpec(StrictModel):
    """A single validated filter expression."""

    column: str = Field(..., min_length=1, max_length=200)
    op: FilterOp
    value: Any = None

    @field_validator("column")
    @classmethod
    def _column_len(cls, value: str) -> str:
        if len(value) > 200:
            raise ValueError("column name too long")
        return value

    @field_validator("value")
    @classmethod
    def _value_size(cls, value: Any) -> Any:
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("filter value too long")
        if isinstance(value, (list, tuple)) and len(value) > 500:
            raise ValueError("filter value list too long")
        return value


class MetricSpec(StrictModel):
    """A single aggregation to compute."""

    column: str | None = Field(default=None, max_length=200)
    agg: Aggregation
    alias: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_ \-]{1,100}$")


# --------------------------------------------------------------------------- #
# Tool inputs
# --------------------------------------------------------------------------- #


class ListDatasetsInput(StrictModel):
    include_demo: bool = True
    search: str | None = Field(default=None, max_length=200)


class InspectSchemaInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)


class PreviewRowsInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    columns: list[str] | None = Field(default=None, max_length=100)


class ProfileDataInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    columns: list[str] | None = Field(default=None, max_length=100)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)


class CheckDataQualityInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    columns: list[str] | None = Field(default=None, max_length=100)


class ApplyFiltersInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    filters: list[FilterSpec] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=100, ge=1, le=5000)
    offset: int = Field(default=0, ge=0)
    sort_by: str | None = Field(default=None, max_length=200)
    sort_dir: SortDir = SortDir.asc


class AggregateMetricsInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    metrics: list[MetricSpec] = Field(..., min_length=1, max_length=12)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    group_by: list[str] | None = Field(default=None, max_length=4)


class GroupByInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    by: list[str] = Field(..., min_length=1, max_length=4)
    metrics: list[MetricSpec] = Field(..., min_length=1, max_length=12)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    sort_by: str | None = Field(default=None, max_length=200)
    sort_dir: SortDir = SortDir.desc
    limit: int = Field(default=100, ge=1, le=5000)


class TimeSeriesInput(StrictModel):
    """Time-bucketed aggregation - the correct way to do 'monthly sales'."""

    dataset_id: str = Field(..., min_length=1, max_length=64)
    date_column: str = Field(..., min_length=1, max_length=200)
    bucket: Literal["day", "week", "month", "quarter", "year"] = "month"
    metrics: list[MetricSpec] = Field(..., min_length=1, max_length=8)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    group_by: list[str] | None = Field(default=None, max_length=2)
    include_growth: bool = True
    period_start: str | None = Field(default=None, max_length=40)
    period_end: str | None = Field(default=None, max_length=40)


class ComputeKPIInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    kpi: str = Field(..., min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    date_column: str | None = Field(default=None, max_length=200)
    group_by: list[str] | None = Field(default=None, max_length=2)
    period: str | None = Field(default=None, max_length=40)
    currency: str = Field(default="USD", max_length=8)
    order: SortDir = SortDir.desc
    limit: int = Field(default=50, ge=1, le=1000)

    @field_validator("params")
    @classmethod
    def _params_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 30:
            raise ValueError("too many KPI parameters")
        for key, value in v.items():
            if len(str(key)) > 100:
                raise ValueError("KPI parameter name too long")
            if isinstance(value, str) and len(value) > 300:
                raise ValueError("KPI parameter value too long")
        return v


class ComparePeriodsInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    date_column: str = Field(..., min_length=1, max_length=200)
    metric_column: str = Field(..., min_length=1, max_length=200)
    agg: Aggregation = Aggregation.sum
    period1_start: str = Field(..., min_length=4, max_length=40)
    period1_end: str = Field(..., min_length=4, max_length=40)
    period2_start: str = Field(..., min_length=4, max_length=40)
    period2_end: str = Field(..., min_length=4, max_length=40)
    group_by: list[str] | None = Field(default=None, max_length=4)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    currency: str = Field(default="USD", max_length=8)


class RankCategoriesInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    category_column: str = Field(..., min_length=1, max_length=200)
    metric_column: str = Field(..., min_length=1, max_length=200)
    agg: Aggregation = Aggregation.sum
    top_n: int = Field(default=10, ge=1, le=200)
    bottom_n: int | None = Field(default=None, ge=1, le=200)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    order: SortDir = SortDir.desc
    currency: str = Field(default="USD", max_length=8)


class DetectOutliersInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    column: str = Field(..., min_length=1, max_length=200)
    method: Literal["iqr", "zscore"] = "iqr"
    threshold: float = Field(default=1.5, gt=0, le=10)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    limit: int = Field(default=20, ge=1, le=200)


class ComputeCorrelationsInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    columns: list[str] = Field(..., min_length=2, max_length=20)
    method: Literal["pearson", "spearman", "kendall"] = "pearson"
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    min_abs: float = Field(default=0.0, ge=0.0, le=1.0)


class ComputeDistributionInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    column: str = Field(..., min_length=1, max_length=200)
    bins: int = Field(default=10, ge=2, le=100)
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)


class JoinApprovedDatasetsInput(StrictModel):
    left_dataset_id: str = Field(..., min_length=1, max_length=64)
    right_dataset_id: str = Field(..., min_length=1, max_length=64)
    left_key: str = Field(..., min_length=1, max_length=200)
    right_key: str = Field(..., min_length=1, max_length=200)
    how: Literal["inner", "left", "right", "full"] = "inner"
    left_columns: list[str] | None = Field(default=None, max_length=50)
    right_columns: list[str] | None = Field(default=None, max_length=50)
    limit: int = Field(default=100, ge=1, le=5000)


class GenerateChartInput(StrictModel):
    dataset_id: str | None = Field(default=None, max_length=64)
    chart_type: ChartType = ChartType.bar
    title: str | None = Field(default=None, max_length=200)
    x: str | None = Field(default=None, max_length=200)
    y: list[str] = Field(default_factory=list, max_length=6)
    group_by: str | None = Field(default=None, max_length=200)
    aggregation: Aggregation | None = None
    bucket: Literal["day", "week", "month", "quarter", "year"] | None = None
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    limit: int = Field(default=200, ge=1, le=2000)
    sort_by: str | None = Field(default=None, max_length=200)
    sort_dir: SortDir = SortDir.desc
    currency: str = Field(default="USD", max_length=8)


class ExportResultsInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    format: Literal["csv", "xlsx", "json"] = "csv"
    filters: list[FilterSpec] | None = Field(default=None, max_length=20)
    columns: list[str] | None = Field(default=None, max_length=100)
    limit: int = Field(default=1000, ge=1, le=50_000)
    sort_by: str | None = Field(default=None, max_length=200)
    sort_dir: SortDir = SortDir.asc


class ExplainCalculationInput(StrictModel):
    dataset_id: str = Field(..., min_length=1, max_length=64)
    calculation: str = Field(..., min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
