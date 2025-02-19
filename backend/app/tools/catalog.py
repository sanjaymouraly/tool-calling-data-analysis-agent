"""The restricted analysis tool library.

Every tool is deterministic, side-effect free (except ``export_results``,
which produces a downloadable artefact) and fully described by a strict
Pydantic input model.

Implementation rules followed by every handler in this module:

* identifiers are validated against the dataset's own column list;
* values are always bound as query parameters;
* the result carries an ``evidence`` block with the dataset id, content hash,
  row counts and the filters that were applied.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..core.errors import SecurityError, ValidationError
from ..core.money import absolute_change, format_money, percent_change, quantize_money
from ..core.periods import bucket_bounds
from ..core.security import sanitize_export_cell
from ..db.models import ApprovedJoin, Dataset, MetricDefinition
from ..domain.kpis import KPI_CATALOGUE, param_for_role, resolve_role
from ..domain.tool_specs import (
    AggregateMetricsInput,
    ApplyFiltersInput,
    CheckDataQualityInput,
    ComparePeriodsInput,
    ComputeCorrelationsInput,
    ComputeDistributionInput,
    ComputeKPIInput,
    DetectOutliersInput,
    ExplainCalculationInput,
    ExportResultsInput,
    GenerateChartInput,
    GroupByInput,
    InspectSchemaInput,
    JoinApprovedDatasetsInput,
    ListDatasetsInput,
    PreviewRowsInput,
    ProfileDataInput,
    RankCategoriesInput,
    TimeSeriesInput,
)
from ..engine.duck import (
    agg_expression,
    build_grouped_aggregate,
    build_single_aggregate,
    build_where,
    execute_dataframe,
    execute_scalar,
    quote_identifier,
    source_clause,
)
from ..ingest import store
from .base import ToolContext, ToolOutcome, register_tool
from .chart import sanitize_text, validate_chart_spec

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _dataset(ctx: ToolContext, dataset_id: str) -> Dataset:
    ctx.authorize(dataset_id)
    return store.get_dataset(ctx.db, dataset_id)


def _columns(dataset: Dataset) -> list[dict[str, Any]]:
    return list((dataset.schema_json or {}).get("columns", []))


def _column_names(dataset: Dataset) -> list[str]:
    return [str(c["name"]) for c in _columns(dataset)]


def _artifact(dataset: Dataset) -> str:
    return store.artifact_for(dataset)


def _evidence(dataset: Dataset, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "file_hash": dataset.source_hash,
        "artifact_hash": dataset.artifact_hash,
        "dataset_version": dataset.version,
        "sheet": dataset.sheet_name,
        "row_count": dataset.row_count,
        "columns": dataset.column_count,
    }
    payload.update(extra)
    return payload


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if (math.isnan(number) or math.isinf(number)) else number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, str, bool)):
        return value
    return str(value)


def _rows_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): _jsonable(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def _count_rows(sql: str, params: Sequence[Any]) -> int:
    value = execute_scalar(sql, params)
    return int(value or 0)


def _to_date(value: str) -> date:
    text = str(value).strip()
    for parser in (date.fromisoformat, lambda t: datetime.fromisoformat(t).date()):
        try:
            return parser(text)
        except ValueError:
            continue
    try:
        return pd.Timestamp(text).date()
    except Exception as exc:
        raise ValidationError(f"could not interpret '{value}' as a date") from exc


def _resolve_period_bounds(start: str, end: str) -> tuple[date, date]:
    start_date = _to_date(start)
    end_date = _to_date(end)
    if end_date < start_date:
        raise ValidationError("the period end date is before the start date")
    return start_date, end_date


def _redact(column: dict[str, Any], samples: list[Any]) -> list[Any]:
    """Never expose values of columns that look like personal data."""
    if column.get("role_hint") == "email":
        return ["[redacted]"] * min(len(samples), 3)
    return samples


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


@register_tool(
    "list_datasets",
    description="List the datasets the user has authorised for this analysis, with row counts and columns.",
    input_model=ListDatasetsInput,
    category="discovery",
    requires_dataset=False,
    output_description="A list of authorised datasets with their identifiers, row counts and column names.",
)
def tool_list_datasets(ctx: ToolContext, args: ListDatasetsInput) -> ToolOutcome:
    datasets = store.list_datasets(ctx.db, include_demo=args.include_demo, search=args.search, limit=100)
    authorised = set(ctx.authorized_dataset_ids)
    rows = []
    for dataset in datasets:
        if authorised and dataset.id not in authorised:
            continue
        rows.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "row_count": dataset.row_count,
                "column_count": dataset.column_count,
                "file_type": dataset.file_type,
                "sheet": dataset.sheet_name,
                "is_demo": dataset.is_demo,
                "is_approved": dataset.is_approved,
                "columns": _column_names(dataset),
                "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
            }
        )
    return ToolOutcome(
        data={"datasets": rows, "count": len(rows)},
        evidence={"source": "application metadata", "dataset_ids": [r["id"] for r in rows]},
    )


@register_tool(
    "inspect_schema",
    description="Inspect the schema of a dataset: column names, inferred types, missing values and roles.",
    input_model=InspectSchemaInput,
    category="discovery",
    output_description="Column-level schema with inferred types, missing-value counts, role hints and sample values.",
)
def tool_inspect_schema(ctx: ToolContext, args: InspectSchemaInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    columns = _columns(dataset)
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "columns": [
                {
                    "name": c.get("name"),
                    "type": c.get("inferred_type"),
                    "role_hint": c.get("role_hint"),
                    "missing_pct": c.get("missing_pct", 0.0),
                    "nullable": c.get("nullable"),
                    "unique_count": c.get("unique_count"),
                    "sample_values": _redact(c, list(c.get("sample_values", []))[:3]),
                }
                for c in columns
            ],
            "warnings": (dataset.schema_json or {}).get("warnings", []),
        },
        evidence=_evidence(dataset),
    )


@register_tool(
    "preview_rows",
    description="Return a bounded sample of rows so the values behind an aggregate can be inspected.",
    input_model=PreviewRowsInput,
    category="discovery",
    output_description="A page of rows plus the total row count of the dataset.",
)
def tool_preview_rows(ctx: ToolContext, args: PreviewRowsInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    if args.columns:
        missing = [c for c in args.columns if c not in allowed]
        if missing:
            raise ValidationError(
                f"columns not found in the dataset: {', '.join(missing[:10])}",
                details={"available_columns": allowed[:50]},
            )
        select_list = ", ".join(quote_identifier(c, allowed) for c in args.columns)
    else:
        select_list = "*"

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    sql = f"SELECT {select_list} FROM {source} LIMIT {int(args.limit)} OFFSET {int(args.offset)}"
    frame = execute_dataframe(sql, params)
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "rows": _rows_to_records(frame),
            "columns": [str(c) for c in frame.columns],
            "total_rows": dataset.row_count,
            "limit": args.limit,
            "offset": args.offset,
        },
        evidence=_evidence(dataset, returned_rows=len(frame)),
    )


@register_tool(
    "profile_data",
    description="Compute descriptive statistics for the numeric columns of a dataset.",
    input_model=ProfileDataInput,
    category="discovery",
    output_description="Per-column count, mean, median, standard deviation, min, max and quartiles.",
)
def tool_profile_data(ctx: ToolContext, args: ProfileDataInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    profile = dataset.schema_json or {}

    numeric_columns = [
        str(c["name"])
        for c in profile.get("columns", [])
        if c.get("inferred_type") in {"numeric", "currency", "mixed_numeric"}
    ]
    if args.columns:
        unknown = [c for c in args.columns if c not in allowed]
        if unknown:
            raise ValidationError(f"columns not found: {', '.join(unknown[:10])}")
        numeric_columns = [c for c in args.columns if c in numeric_columns]

    summary: dict[str, Any] = {}
    if numeric_columns:
        source, source_params = source_clause(_artifact(dataset))
        params = list(source_params)
        where = build_where(args.filters, allowed, params)
        select_parts = []
        for column in numeric_columns:
            ident = quote_identifier(column, allowed)
            select_parts.extend(
                [
                    f"COUNT({ident}) AS {quote_identifier(column + '__count')}",
                    f"AVG(CAST({ident} AS DECIMAL(18,4))) AS {quote_identifier(column + '__mean')}",
                    f"MEDIAN(CAST({ident} AS DECIMAL(18,4))) AS {quote_identifier(column + '__median')}",
                    f"STDDEV_POP(CAST({ident} AS DECIMAL(18,4))) AS {quote_identifier(column + '__std')}",
                    f"MIN(CAST({ident} AS DECIMAL(18,4))) AS {quote_identifier(column + '__min')}",
                    f"MAX(CAST({ident} AS DECIMAL(18,4))) AS {quote_identifier(column + '__max')}",
                    f"QUANTILE_CONT(CAST({ident} AS DECIMAL(18,4)), 0.25) AS {quote_identifier(column + '__q25')}",
                    f"QUANTILE_CONT(CAST({ident} AS DECIMAL(18,4)), 0.75) AS {quote_identifier(column + '__q75')}",
                ]
            )
        sql = f"SELECT {', '.join(select_parts)} FROM {source}"
        if where:
            sql += f" WHERE {where}"
        frame = execute_dataframe(sql, params)
        if not frame.empty:
            row = frame.iloc[0].to_dict()
            for column in numeric_columns:
                summary[column] = {
                    key.removeprefix(column + "__"): _jsonable(value)
                    for key, value in row.items()
                    if key.startswith(column + "__")
                }

    missing_summary = {
        str(c["name"]): {
            "missing": c.get("missing_count", 0),
            "total": dataset.row_count,
            "pct": c.get("missing_pct", 0.0),
        }
        for c in profile.get("columns", [])
    }

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "row_count": dataset.row_count,
            "column_count": dataset.column_count,
            "numeric_summary": summary,
            "missing_summary": missing_summary,
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(dataset, profiled_columns=numeric_columns),
    )


@register_tool(
    "check_data_quality",
    description="Report missing values, duplicate rows, outliers, type issues and a data-quality score.",
    input_model=CheckDataQualityInput,
    category="discovery",
    output_description="Quality score, missing-value map, duplicate count, outliers per column and actionable warnings.",
)
def tool_check_data_quality(ctx: ToolContext, args: CheckDataQualityInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    report = dict(dataset.quality_json or {})
    report["dataset_id"] = dataset.id
    return ToolOutcome(
        data=report,
        evidence=_evidence(dataset, quality_score=report.get("score")),
    )


# --------------------------------------------------------------------------- #
# Filtering and aggregation
# --------------------------------------------------------------------------- #


@register_tool(
    "apply_filters",
    description="Filter rows with validated predicates and return a bounded page of the matching rows.",
    input_model=ApplyFiltersInput,
    category="query",
    output_description="The filtered rows plus the original and filtered row counts.",
)
def tool_apply_filters(ctx: ToolContext, args: ApplyFiltersInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)

    count_sql = f"SELECT COUNT(*) FROM {source}"
    if where:
        count_sql += f" WHERE {where}"
    total_after = _count_rows(count_sql, params)

    sql = f"SELECT * FROM {source}"
    if where:
        sql += f" WHERE {where}"
    if args.sort_by:
        if args.sort_by not in allowed:
            raise ValidationError(f"sort column '{args.sort_by}' does not exist in this dataset")
        direction = "DESC" if args.sort_dir.value == "desc" else "ASC"
        sql += f" ORDER BY {quote_identifier(args.sort_by, allowed)} {direction} NULLS LAST"
    sql += f" LIMIT {int(args.limit)} OFFSET {int(args.offset)}"
    frame = execute_dataframe(sql, params)

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "original_row_count": dataset.row_count,
            "filtered_row_count": total_after,
            "rows": _rows_to_records(frame),
            "columns": [str(c) for c in frame.columns],
            "filters_applied": [f.model_dump(mode="json") for f in args.filters],
            "limit": args.limit,
            "offset": args.offset,
        },
        evidence=_evidence(
            dataset,
            filters=[f.model_dump(mode="json") for f in args.filters],
            row_counts={"original": dataset.row_count, "filtered": total_after},
        ),
    )


@register_tool(
    "aggregate_metrics",
    description="Compute one or more aggregations over the whole dataset, optionally grouped.",
    input_model=AggregateMetricsInput,
    category="query",
    output_description="One row of aggregate values, or one row per group.",
)
def tool_aggregate_metrics(ctx: ToolContext, args: AggregateMetricsInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)

    if args.group_by:
        query = build_grouped_aggregate(
            artifact_path=_artifact(dataset),
            group_by=args.group_by,
            metrics=args.metrics,
            filters=args.filters,
            allowed_columns=allowed,
            limit=ctx.settings.max_tool_result_rows,
        )
    else:
        query = build_single_aggregate(
            artifact_path=_artifact(dataset),
            metrics=args.metrics,
            filters=args.filters,
            allowed_columns=allowed,
        )
    frame = execute_dataframe(query.sql, query.params)
    results = _rows_to_records(frame)

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "results": results,
            "row_count": len(results),
            "group_by": args.group_by or [],
            "metrics": [m.model_dump(mode="json") for m in args.metrics],
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
            aggregate="grouped" if args.group_by else "whole dataset",
        ),
    )


@register_tool(
    "group_by",
    description="Group the dataset by one or more dimensions and aggregate metrics for each group.",
    input_model=GroupByInput,
    category="query",
    output_description="One row per group with the requested aggregations, sorted and truncated.",
)
def tool_group_by(ctx: ToolContext, args: GroupByInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    query = build_grouped_aggregate(
        artifact_path=_artifact(dataset),
        group_by=args.by,
        metrics=args.metrics,
        filters=args.filters,
        allowed_columns=allowed,
        order_by=args.sort_by,
        order_dir=args.sort_dir.value,
        limit=min(args.limit, ctx.settings.max_tool_result_rows),
    )
    frame = execute_dataframe(query.sql, query.params)
    results = _rows_to_records(frame)
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "by": args.by,
            "results": results,
            "row_count": len(results),
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            group_by=args.by,
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
            group_count=len(results),
        ),
    )


def _bucket_expression(bucket: str, ident: str) -> str:
    return {
        "day": f"strftime(CAST({ident} AS TIMESTAMP), '%Y-%m-%d')",
        "week": f"strftime(CAST({ident} AS TIMESTAMP), '%G-W%V')",
        "month": f"strftime(CAST({ident} AS TIMESTAMP), '%Y-%m')",
        "quarter": (
            f"strftime(CAST({ident} AS TIMESTAMP), '%Y') || '-Q' || "
            f"CAST(QUARTER(CAST({ident} AS TIMESTAMP)) AS VARCHAR)"
        ),
        "year": f"strftime(CAST({ident} AS TIMESTAMP), '%Y')",
    }[bucket]


@register_tool(
    "time_series",
    description=(
        "Bucket rows by a date column (day/week/month/quarter/year) and aggregate metrics per bucket, "
        "with period-over-period growth."
    ),
    input_model=TimeSeriesInput,
    category="query",
    output_description="One row per time bucket with the aggregated metric and the growth versus the previous bucket.",
)
def tool_time_series(ctx: ToolContext, args: TimeSeriesInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    if args.date_column not in allowed:
        raise ValidationError(
            f"date column '{args.date_column}' does not exist in this dataset",
            details={"available_columns": allowed[:50]},
        )
    for column in args.group_by or []:
        if column not in allowed:
            raise ValidationError(f"group column '{column}' does not exist in this dataset")

    bucket_expr = _bucket_expression(args.bucket, quote_identifier(args.date_column, allowed))

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)

    select_parts = [f"{bucket_expr} AS {quote_identifier('period')}"]
    for metric in args.metrics:
        agg = metric.agg.value if hasattr(metric.agg, "value") else str(metric.agg)
        alias = metric.alias or f"{metric.column or 'rows'}_{agg}"
        if agg == "count" and not metric.column:
            select_parts.append(f"COUNT(*) AS {quote_identifier(alias)}")
            continue
        if not metric.column:
            raise ValidationError(f"aggregation '{agg}' requires a column")
        if metric.column not in allowed:
            raise ValidationError(f"metric column '{metric.column}' does not exist in this dataset")
        ident = quote_identifier(metric.column, allowed)
        expr = f"CAST({ident} AS DECIMAL(18,4))" if agg in {"sum", "mean", "median", "min", "max"} else ident
        select_parts.append(f"{agg_expression(agg, expr)} AS {quote_identifier(alias)}")

    group_exprs = [bucket_expr]
    if args.group_by:
        for column in args.group_by:
            group_exprs.append(quote_identifier(column, allowed))
            select_parts.append(f"{quote_identifier(column, allowed)} AS {quote_identifier(column)}")

    sql = f"SELECT {', '.join(select_parts)} FROM {source}"
    if where:
        sql += f" WHERE {where}"
    sql += f" GROUP BY {', '.join(group_exprs)} ORDER BY {quote_identifier('period')}"

    frame = execute_dataframe(sql, params)
    records = _rows_to_records(frame)

    if args.period_start or args.period_end:
        start = _to_date(args.period_start) if args.period_start else None
        end = _to_date(args.period_end) if args.period_end else None
        filtered = []
        for record in records:
            try:
                bucket_start, bucket_end = bucket_bounds(str(record["period"]), args.bucket)
            except Exception:
                filtered.append(record)
                continue
            if start and bucket_end < start:
                continue
            if end and bucket_start > end:
                continue
            filtered.append(record)
        records = filtered

    metric_aliases = [
        m.alias or f"{m.column or 'rows'}_{m.agg.value if hasattr(m.agg, 'value') else m.agg}"
        for m in args.metrics
    ]

    if args.include_growth and metric_aliases:
        alias = metric_aliases[0]
        previous_value: float | None = None
        for record in records:
            current = record.get(alias)
            change, note = percent_change(current, previous_value)
            record["previous_value"] = previous_value
            record["change"] = (
                absolute_change(current, previous_value) if previous_value is not None else None
            )
            record["growth_pct"] = change
            record["growth_note"] = note
            if isinstance(current, (int, float)):
                previous_value = float(current)

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "bucket": args.bucket,
            "date_column": args.date_column,
            "periods": records,
            "row_count": len(records),
            "metrics": [m.model_dump(mode="json") for m in args.metrics],
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            bucket=args.bucket,
            date_column=args.date_column,
            period_count=len(records),
            first_period=records[0]["period"] if records else None,
            last_period=records[-1]["period"] if records else None,
        ),
    )


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #


def _approved_metric_params(ctx: ToolContext, dataset: Dataset, kpi: str) -> dict[str, Any] | None:
    statement = select(MetricDefinition).where(
        MetricDefinition.is_approved.is_(True),
        MetricDefinition.kpi == kpi,
    )
    definition = ctx.db.execute(statement).scalars().first()
    if definition is None:
        return None
    if definition.dataset_id and definition.dataset_id != dataset.id:
        return None
    return dict(definition.params_json or {})


def _resolve_kpi_columns(
    ctx: ToolContext,
    dataset: Dataset,
    definition,
    params: dict[str, Any],
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Resolve every role the KPI needs into ``(column, resolution)`` pairs."""
    columns = _columns(dataset)
    available = {str(c["name"]) for c in columns}
    approved = _approved_metric_params(ctx, dataset, definition.name)
    resolved: dict[str, tuple[str, str]] = {}
    missing: list[str] = []

    for role in definition.required_roles:
        explicit = param_for_role(params, role)
        if explicit is None and approved:
            explicit = param_for_role(approved, role)
        column, resolution = resolve_role(role, columns, explicit)
        if column is None or column not in available:
            missing.append(role)
            continue
        resolved[role] = (column, resolution)
    return resolved, missing


@register_tool(
    "compute_kpi",
    description=(
        "Compute a supported business KPI (revenue, AOV, margin, conversion, churn, on-time delivery, ...). "
        "Requires explicit or clearly reported column mappings; it never guesses an unsupported KPI. "
        "Can be computed per group (for example on-time delivery percentage per supplier)."
    ),
    input_model=ComputeKPIInput,
    category="kpi",
    output_description="The KPI value, its formula, the columns it used and how those columns were resolved.",
)
def tool_compute_kpi(ctx: ToolContext, args: ComputeKPIInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    definition = KPI_CATALOGUE.get(args.kpi)
    if definition is None:
        raise ValidationError(
            f"KPI '{args.kpi}' is not supported",
            details={"supported_kpis": sorted(KPI_CATALOGUE)},
        )

    resolved, missing = _resolve_kpi_columns(ctx, dataset, definition, args.params)
    if missing:
        raise ValidationError(
            f"KPI '{definition.label}' needs a column for: {', '.join(missing)}. "
            "Map them explicitly (for example revenue_column=Revenue) or approve a metric definition.",
            details={
                "missing_roles": missing,
                "available_columns": allowed,
                "kpi": definition.name,
            },
        )

    group_by = args.group_by or []
    for column in group_by:
        if column not in allowed:
            raise ValidationError(
                f"group column '{column}' does not exist in this dataset",
                details={"available_columns": allowed[:50]},
            )

    if definition.name in {"repeat_purchase_rate", "sales_growth"} and group_by:
        raise ValidationError(
            f"the {definition.label} KPI cannot be computed per group; run it for the whole dataset "
            "and group the result yourself.",
            details={"kpi": definition.name},
        )

    source, source_params = source_clause(_artifact(dataset))
    base_params = list(source_params)
    where = build_where(args.filters, allowed, base_params)

    if definition.name == "sales_growth":
        return _sales_growth_outcome(dataset, allowed, definition, resolved, args)
    if definition.name == "repeat_purchase_rate":
        return _repeat_purchase_outcome(dataset, allowed, definition, resolved, args, where, base_params)

    expression, formula, extra_params, notes = _kpi_expression(definition, resolved, allowed, args)

    select_parts = []
    for column in group_by:
        select_parts.append(f"{quote_identifier(column, allowed)} AS {quote_identifier(column)}")
    select_parts.append(f"({expression}) AS {quote_identifier('value')}")

    sql = f"SELECT {', '.join(select_parts)} FROM {source}"
    if where:
        sql += f" WHERE {where}"
    if group_by:
        sql += f" GROUP BY {', '.join(quote_identifier(c, allowed) for c in group_by)}"

    direction = "DESC" if args.order.value == "desc" else "ASC"
    sql += f" ORDER BY {quote_identifier('value')} {direction} NULLS LAST"
    sql += f" LIMIT {int(args.limit)}"

    params = [*base_params, *extra_params]
    frame = execute_dataframe(sql, params)

    row_count = _count_rows(
        f"SELECT COUNT(*) FROM {source}" + (f" WHERE {where}" if where else ""), base_params
    )

    records = _rows_to_records(frame)
    resolution_report = {
        role: {"column": column, "resolution": resolution} for role, (column, resolution) in resolved.items()
    }

    if group_by:
        groups: list[dict[str, Any]] = []
        for record in records:
            value = record.get("value")
            groups.append(
                {
                    "group": " | ".join(
                        "(missing)" if record.get(c) is None else str(record.get(c)) for c in group_by
                    ),
                    "group_values": {c: record.get(c) for c in group_by},
                    "value": value,
                    "display_value": (
                        format_money(value, args.currency)
                        if definition.unit == "currency" and value is not None
                        else (
                            f"{value:,.2f}%" if definition.unit == "percent" and value is not None else value
                        )
                    ),
                }
            )
        return ToolOutcome(
            data={
                "dataset_id": dataset.id,
                "kpi": definition.name,
                "label": definition.label,
                "grouped_by": group_by,
                "groups": groups,
                "row_count": len(groups),
                "unit": definition.unit,
                "currency": args.currency if definition.unit == "currency" else None,
                "formula": formula,
                "column_resolution": resolution_report,
                "notes": notes,
                "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
            },
            evidence=_evidence(
                dataset,
                kpi=definition.name,
                formula=formula,
                group_by=group_by,
                columns_used=[column for column, _ in resolved.values()],
                column_resolution=resolution_report,
                row_count=row_count,
                filters=[f.model_dump(mode="json") for f in (args.filters or [])],
            ),
        )

    value = records[0].get("value") if records else None
    details: dict[str, Any] = {"row_count": row_count}
    if definition.name == "average_order_value":
        money = resolved["money"][0]
        order_id = resolved["order_id"][0]
        total = execute_scalar(
            f"SELECT SUM(CAST({quote_identifier(money, allowed)} AS DECIMAL(18,4))) FROM {source}"
            + (f" WHERE {where}" if where else ""),
            base_params,
        )
        distinct = execute_scalar(
            f"SELECT COUNT(DISTINCT {quote_identifier(order_id, allowed)}) FROM {source}"
            + (f" WHERE {where}" if where else ""),
            base_params,
        )
        details["total_revenue"] = quantize_money(float(total or 0.0))
        details["distinct_orders"] = int(distinct or 0)
    if definition.name == "average_order_value":
        details["note"] = "Computed as total revenue divided by the number of distinct orders."
    if notes:
        details["note"] = notes

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "kpi": definition.name,
            "label": definition.label,
            "value": value,
            "unit": definition.unit,
            "currency": args.currency if definition.unit == "currency" else None,
            "display_value": (
                format_money(value, args.currency)
                if definition.unit == "currency" and value is not None
                else (f"{value:,.2f}%" if definition.unit == "percent" and value is not None else value)
            ),
            "formula": formula,
            "column_resolution": resolution_report,
            "details": details,
            "row_count": row_count,
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            kpi=definition.name,
            formula=formula,
            columns_used=[column for column, _ in resolved.values()],
            column_resolution=resolution_report,
            row_count=row_count,
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
        ),
    )


def _sales_growth_outcome(
    dataset: Dataset,
    allowed: list[str],
    definition,
    resolved: dict[str, tuple[str, str]],
    args: ComputeKPIInput,
) -> ToolOutcome:
    """Period-over-period revenue growth (the only KPI that is not a plain ratio)."""
    date_column = resolved["date"][0]
    money_column = resolved["money"][0]
    period_spec = args.period
    if not period_spec:
        period_spec = _latest_period_label(date_column, dataset)
    if not period_spec:
        raise ValidationError(
            "sales growth needs an explicit period (for example 2024-Q1) because the date range is unknown",
            details={"available_columns": allowed},
        )
    current = _resolve_period(period_spec)
    previous = _previous_period(period_spec)
    current_value = _period_value(dataset, allowed, date_column, money_column, current)
    previous_value = _period_value(dataset, allowed, date_column, money_column, previous)
    change, note = percent_change(current_value, previous_value)
    formula = (
        f"(SUM({money_column} in {current.label}) - SUM({money_column} in {previous.label})) "
        f"/ SUM({money_column} in {previous.label}) * 100"
    )
    resolution_report = {
        role: {"column": column, "resolution": resolution} for role, (column, resolution) in resolved.items()
    }
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "kpi": definition.name,
            "label": definition.label,
            "value": change,
            "unit": "percent",
            "display_value": f"{change:,.2f}%" if change is not None else "undefined",
            "formula": formula,
            "column_resolution": resolution_report,
            "details": {
                "current_period": current.as_dict(),
                "previous_period": previous.as_dict(),
                "current_value": quantize_money(current_value),
                "previous_value": quantize_money(previous_value),
                "absolute_change": absolute_change(current_value, previous_value),
                "note": note,
            },
            "row_count": dataset.row_count,
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            kpi=definition.name,
            formula=formula,
            columns_used=[column for column, _ in resolved.values()],
            column_resolution=resolution_report,
            period_current=current.as_dict(),
            period_previous=previous.as_dict(),
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
        ),
    )


def _repeat_purchase_outcome(
    dataset: Dataset,
    allowed: list[str],
    definition,
    resolved: dict[str, tuple[str, str]],
    args: ComputeKPIInput,
    where: str,
    base_params: list[Any],
) -> ToolOutcome:
    """Share of customers with more than one order."""
    source, _source_params = source_clause(_artifact(dataset))
    customer = quote_identifier(resolved["customer_id"][0], allowed)
    order = quote_identifier(resolved["order_id"][0], allowed)
    sql = (
        f"SELECT COUNT(*) FILTER (WHERE order_count > 1) * 100.0 / NULLIF(COUNT(*), 0) AS value, "
        f"COUNT(*) AS customers FROM (SELECT {customer} AS customer_id, "
        f"COUNT(DISTINCT {order}) AS order_count FROM {source}"
        + (f" WHERE {where}" if where else "")
        + " GROUP BY 1) AS per_customer"
    )
    frame = execute_dataframe(sql, list(base_params))
    value = None
    customers = 0
    if not frame.empty:
        value = frame.iloc[0].get("value")
        customers = int(frame.iloc[0].get("customers") or 0)
    resolution_report = {
        role: {"column": column, "resolution": resolution} for role, (column, resolution) in resolved.items()
    }
    formula = f"customers with >1 {resolved['order_id'][0]} / distinct {resolved['customer_id'][0]} * 100"
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "kpi": definition.name,
            "label": definition.label,
            "value": _jsonable(value),
            "unit": definition.unit,
            "display_value": f"{value:,.2f}%" if value is not None else "undefined",
            "formula": formula,
            "column_resolution": resolution_report,
            "details": {"distinct_customers": customers},
            "row_count": dataset.row_count,
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            kpi=definition.name,
            formula=formula,
            columns_used=[column for column, _ in resolved.values()],
            column_resolution=resolution_report,
            distinct_customers=customers,
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
        ),
    )


def _kpi_expression(
    definition,
    resolved: dict[str, tuple[str, str]],
    allowed: list[str],
    args: ComputeKPIInput,
) -> tuple[str, str, list[Any], str]:
    """Build the SQL expression of a KPI.

    Returns ``(expression, formula, extra_parameters, note)``.  The expression
    is a pure function of the resolved columns so it can be used both for a
    whole-dataset KPI and for a per-group KPI.
    """

    def ident(role: str) -> str:
        return quote_identifier(resolved[role][0], allowed)

    name = definition.name
    notes = ""

    if name == "revenue":
        expr = f"SUM(CAST({ident('money')} AS DECIMAL(18,4)))"
        return expr, f"SUM({resolved['money'][0]})", [], notes

    if name == "average_order_value":
        money = ident("money")
        order = ident("order_id")
        expr = (
            f"CASE WHEN COUNT(DISTINCT {order}) = 0 THEN NULL "
            f"ELSE SUM(CAST({money} AS DECIMAL(18,4))) / COUNT(DISTINCT {order}) END"
        )
        return (
            expr,
            f"SUM({resolved['money'][0]}) / COUNT(DISTINCT {resolved['order_id'][0]})",
            [],
            notes,
        )

    if name in {"gross_margin_amount", "gross_margin_pct"}:
        money = ident("money")
        cost = ident("cost")
        if name == "gross_margin_amount":
            expr = f"SUM(CAST({money} AS DECIMAL(18,4))) - SUM(CAST({cost} AS DECIMAL(18,4)))"
            return expr, f"SUM({resolved['money'][0]}) - SUM({resolved['cost'][0]})", [], notes
        expr = (
            f"CASE WHEN SUM(CAST({money} AS DECIMAL(18,4))) = 0 THEN NULL "
            f"ELSE (SUM(CAST({money} AS DECIMAL(18,4))) - SUM(CAST({cost} AS DECIMAL(18,4)))) "
            f"/ SUM(CAST({money} AS DECIMAL(18,4))) * 100 END"
        )
        return (
            expr,
            f"(SUM({resolved['money'][0]}) - SUM({resolved['cost'][0]})) / SUM({resolved['money'][0]}) * 100",
            [],
            "Undefined (NULL) when revenue is zero.",
        )

    if name == "units_sold":
        expr = f"SUM(CAST({ident('quantity')} AS DECIMAL(18,4)))"
        return expr, f"SUM({resolved['quantity'][0]})", [], notes

    if name == "average_unit_price":
        expr = f"AVG(CAST({ident('unit_price')} AS DECIMAL(18,4)))"
        return expr, f"AVG({resolved['unit_price'][0]})", [], notes

    if name == "effective_discount_pct":
        expr = f"AVG(CAST({ident('discount')} AS DECIMAL(18,4))) * 100"
        return expr, f"AVG({resolved['discount'][0]}) * 100", [], notes

    if name in {"conversion_rate", "churn_rate", "return_rate"}:
        role = {
            "conversion_rate": "conversion_flag",
            "churn_rate": "churn_flag",
            "return_rate": "returned_flag",
        }[name]
        column = ident(role)
        expr = (
            f"COUNT(*) FILTER (WHERE LOWER(CAST({column} AS VARCHAR)) IN "
            "('true','yes','y','1','t','converted','churned','cancelled','canceled','returned','refunded')) "
            "* 100.0 / NULLIF(COUNT(*), 0)"
        )
        return expr, f"COUNT({resolved[role][0]} = true) / COUNT(*) * 100", [], notes

    if name == "on_time_delivery_pct":
        if "expected_date" in resolved and "actual_date" in resolved:
            expected = ident("expected_date")
            actual = ident("actual_date")
            expr = (
                f"COUNT(*) FILTER (WHERE CAST({actual} AS DATE) <= CAST({expected} AS DATE)) * 100.0 / "
                f"NULLIF(COUNT(*) FILTER (WHERE {expected} IS NOT NULL AND {actual} IS NOT NULL), 0)"
            )
            return (
                expr,
                f"COUNT({resolved['actual_date'][0]} <= {resolved['expected_date'][0]}) / COUNT(comparable) * 100",
                [],
                "Only deliveries with both an expected and an actual date are counted.",
            )
        if "status" in resolved:
            status = ident("status")
            on_time_value = str(args.params.get("on_time_value", "on time")).lower()
            expr = (
                f"COUNT(*) FILTER (WHERE LOWER(CAST({status} AS VARCHAR)) = ?) * 100.0 / NULLIF(COUNT(*), 0)"
            )
            return (
                expr,
                f"COUNT({resolved['status'][0]} = '{on_time_value}') / COUNT(*) * 100",
                [on_time_value],
                "Every row of the dataset is counted as a delivery.",
            )
        raise ValidationError(
            "on-time delivery needs either an expected/actual date pair or a status column",
            details={"available_columns": allowed},
        )

    if name == "inventory_turnover":
        quantity = ident("quantity")
        inventory = ident("inventory_on_hand")
        expr = f"SUM(CAST({quantity} AS DECIMAL(18,4))) / NULLIF(AVG(CAST({inventory} AS DECIMAL(18,4))), 0)"
        return expr, f"SUM({resolved['quantity'][0]}) / AVG({resolved['inventory_on_hand'][0]})", [], notes

    raise ValidationError(f"KPI '{definition.name}' is not implemented")


def _dataset_for_period(args: ComputeKPIInput, ctx: ToolContext) -> Dataset:
    return store.get_dataset(ctx.db, args.dataset_id)


def _resolve_period(spec: str):
    from ..core.periods import resolve_period

    try:
        return resolve_period(spec)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _previous_period(spec: str):
    from ..core.periods import previous_period

    try:
        return previous_period(spec)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _latest_period_label(date_column: str, dataset: Dataset) -> str | None:
    """Return the most recent calendar period present in a date column."""
    allowed = _column_names(dataset)
    if date_column not in allowed:
        return None
    source, source_params = source_clause(_artifact(dataset))
    sql = (
        f"SELECT strftime(CAST({quote_identifier(date_column, allowed)} AS TIMESTAMP), '%Y-%m') AS period "
        f"FROM {source} WHERE {quote_identifier(date_column, allowed)} IS NOT NULL "
        "GROUP BY 1 ORDER BY 1 DESC LIMIT 1"
    )
    frame = execute_dataframe(sql, source_params)
    if frame.empty:
        return None
    return str(frame.iloc[0]["period"])


def _period_value(
    dataset: Dataset,
    allowed: list[str],
    date_column: str,
    metric_column: str,
    period,
) -> float:
    source, source_params = source_clause(_artifact(dataset))
    sql = (
        f"SELECT SUM(CAST({quote_identifier(metric_column, allowed)} AS DECIMAL(18,4))) AS value FROM {source} "
        f"WHERE CAST({quote_identifier(date_column, allowed)} AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"
    )
    params = [*source_params, period.start.isoformat(), period.end.isoformat()]
    return float(execute_scalar(sql, params) or 0.0)


@register_tool(
    "compare_periods",
    description=(
        "Compare two explicit date periods for a metric, in total and optionally per group, "
        "reporting absolute and percentage change."
    ),
    input_model=ComparePeriodsInput,
    category="kpi",
    output_description="Per-period values with absolute and percentage change, and per-group breakdown.",
)
def tool_compare_periods(ctx: ToolContext, args: ComparePeriodsInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    for column in [args.date_column, args.metric_column, *(args.group_by or [])]:
        if column not in allowed:
            raise ValidationError(
                f"column '{column}' does not exist in this dataset",
                details={"available_columns": allowed[:50]},
            )

    period1 = _resolve_period_bounds(args.period1_start, args.period1_end)
    period2 = _resolve_period_bounds(args.period2_start, args.period2_end)
    source, source_params = source_clause(_artifact(dataset))
    base_params = list(source_params)
    where = build_where(args.filters, allowed, base_params)
    date_ident = quote_identifier(args.date_column, allowed)
    metric_ident = quote_identifier(args.metric_column, allowed)

    def period_query(start: date, end: date, group_by: list[str] | None):
        params = list(base_params)
        select_parts = []
        if group_by:
            for column in group_by:
                select_parts.append(quote_identifier(column, allowed))
            group_clause = f" GROUP BY {', '.join(quote_identifier(c, allowed) for c in group_by)}"
        else:
            group_clause = ""
        expr = f"CAST({metric_ident} AS DECIMAL(18,4))"
        select_parts.append(f"{agg_expression(args.agg.value, expr)} AS {quote_identifier('value')}")
        sql = (
            f"SELECT {', '.join(select_parts)} FROM {source}"
            + (f" WHERE {where} AND " if where else " WHERE ")
            + f"CAST({date_ident} AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"
            + group_clause
        )
        params.extend([start.isoformat(), end.isoformat()])
        return execute_dataframe(sql, params)

    frame1 = period_query(period1[0], period1[1], args.group_by)
    frame2 = period_query(period2[0], period2[1], args.group_by)

    def to_map(frame: pd.DataFrame) -> dict[str, float]:
        mapping: dict[str, float] = {}
        if frame.empty:
            return mapping
        for row in frame.to_dict(orient="records"):
            if args.group_by:
                key = " | ".join(
                    "(missing)" if row.get(c) is None else str(row.get(c)) for c in args.group_by
                )
            else:
                key = "total"
            mapping[key] = float(row.get("value") or 0.0)
        return mapping

    map1, map2 = to_map(frame1), to_map(frame2)
    keys = sorted(set(map1) | set(map2))
    comparisons: list[dict[str, Any]] = []
    for key in keys:
        value1 = map1.get(key, 0.0)
        value2 = map2.get(key, 0.0)
        change, note = percent_change(value2, value1)
        comparisons.append(
            {
                "group": key,
                "period1_value": quantize_money(value1),
                "period2_value": quantize_money(value2),
                "absolute_change": absolute_change(value2, value1),
                "percent_change": change,
                "percent_change_note": note,
            }
        )

    total1 = sum(map1.values())
    total2 = sum(map2.values())
    total_change, total_note = percent_change(total2, total1)

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "metric": args.metric_column,
            "aggregation": args.agg.value,
            "period1": {
                "start": period1[0].isoformat(),
                "end": period1[1].isoformat(),
                "value": quantize_money(total1),
                "row_count": int(len(frame1)),
            },
            "period2": {
                "start": period2[0].isoformat(),
                "end": period2[1].isoformat(),
                "value": quantize_money(total2),
                "row_count": int(len(frame2)),
            },
            "absolute_change": absolute_change(total2, total1),
            "percent_change": total_change,
            "percent_change_note": total_note,
            "comparisons": comparisons,
            "group_by": args.group_by or [],
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            metric=args.metric_column,
            aggregation=args.agg.value,
            period1={"start": period1[0].isoformat(), "end": period1[1].isoformat()},
            period2={"start": period2[0].isoformat(), "end": period2[1].isoformat()},
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
        ),
    )


@register_tool(
    "rank_categories",
    description="Rank categories of a column by an aggregated metric, with optional top-N / bottom-N and share of total.",
    input_model=RankCategoriesInput,
    category="query",
    output_description="Ranked categories with values, rank and share of the total.",
)
def tool_rank_categories(ctx: ToolContext, args: RankCategoriesInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    for column in (args.category_column, args.metric_column):
        if column not in allowed:
            raise ValidationError(
                f"column '{column}' does not exist in this dataset",
                details={"available_columns": allowed[:50]},
            )

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)
    metric_ident = quote_identifier(args.metric_column, allowed)
    expr = f"CAST({metric_ident} AS DECIMAL(18,4))"
    agg = args.agg.value
    sql = (
        f"SELECT {quote_identifier(args.category_column, allowed)} AS {quote_identifier('category')}, "
        f"{agg_expression(agg, expr)} AS {quote_identifier('value')} FROM {source}"
    )
    if where:
        sql += f" WHERE {where}"
    sql += f" GROUP BY {quote_identifier(args.category_column, allowed)}"
    frame = execute_dataframe(sql, params)
    records = _rows_to_records(frame)
    records = [r for r in records if r.get("category") is not None]
    total = sum(float(r.get("value") or 0.0) for r in records)

    ordered = sorted(records, key=lambda r: (r.get("value") is None, -(r.get("value") or 0.0)))
    if args.order.value == "asc":
        ordered = list(reversed(ordered))

    ranked: list[dict[str, Any]] = []
    for index, record in enumerate(ordered, start=1):
        value = float(record.get("value") or 0.0)
        share = round(value / total * 100, 2) if total else None
        ranked.append(
            {
                "rank": index,
                "category": record.get("category"),
                "value": quantize_money(value),
                "share_pct": share,
            }
        )

    top = ranked[: args.top_n]
    bottom = list(reversed(ranked[-args.bottom_n :])) if args.bottom_n else []

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "category_column": args.category_column,
            "metric_column": args.metric_column,
            "aggregation": agg,
            "ranked": top,
            "top": top,
            "bottom": bottom,
            "total": quantize_money(total),
            "category_count": len(ranked),
            "filters": [f.model_dump(mode="json") for f in (args.filters or [])],
        },
        evidence=_evidence(
            dataset,
            category_column=args.category_column,
            metric_column=args.metric_column,
            aggregation=agg,
            total=quantize_money(total),
            category_count=len(ranked),
        ),
    )


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


@register_tool(
    "detect_outliers",
    description="Detect outliers in a numeric column using the IQR or z-score method and return example rows.",
    input_model=DetectOutliersInput,
    category="statistics",
    output_description="Outlier count, percentage, the computed bounds and up to N example outlier rows.",
)
def tool_detect_outliers(ctx: ToolContext, args: DetectOutliersInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    if args.column not in allowed:
        raise ValidationError(
            f"column '{args.column}' does not exist in this dataset",
            details={"available_columns": allowed[:50]},
        )

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)
    ident = quote_identifier(args.column, allowed)
    numeric = f"CAST({ident} AS DECIMAL(18,4))"
    where_clause = f" WHERE {where}" if where else ""

    count = int(execute_scalar(f"SELECT COUNT({numeric}) FROM {source}{where_clause}", params) or 0)
    if count < 5:
        raise ValidationError(f"at least 5 non-null values are required for outlier detection, found {count}")

    if args.method == "iqr":
        q1 = float(
            execute_scalar(f"SELECT QUANTILE_CONT({numeric}, 0.25) FROM {source}{where_clause}", params)
            or 0.0
        )
        q3 = float(
            execute_scalar(f"SELECT QUANTILE_CONT({numeric}, 0.75) FROM {source}{where_clause}", params)
            or 0.0
        )
        iqr = q3 - q1
        lower, upper = q1 - args.threshold * iqr, q3 + args.threshold * iqr
        predicate = f"{numeric} < {lower} OR {numeric} > {upper}"
    else:
        mean = float(execute_scalar(f"SELECT AVG({numeric}) FROM {source}{where_clause}", params) or 0.0)
        std = float(
            execute_scalar(f"SELECT STDDEV_POP({numeric}) FROM {source}{where_clause}", params) or 0.0
        )
        if std == 0:
            lower = upper = mean
            predicate = "FALSE"
        else:
            lower = mean - args.threshold * std
            upper = mean + args.threshold * std
            predicate = f"ABS(({numeric} - {mean}) / {std}) > {args.threshold}"

    outlier_sql = f"SELECT * FROM {source}"
    if where:
        outlier_sql += f" WHERE ({where}) AND ({predicate})"
    else:
        outlier_sql += f" WHERE {predicate}"
    outlier_sql += f" LIMIT {int(args.limit)}"
    frame = execute_dataframe(outlier_sql, params)
    outlier_count = int(
        execute_scalar(
            f"SELECT COUNT(*) FROM (SELECT 1 FROM {source}"
            + (f" WHERE {where} AND ({predicate})" if where else f" WHERE {predicate}")
            + ")",
            params,
        )
        or 0
    )

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "column": args.column,
            "method": args.method,
            "threshold": args.threshold,
            "bounds": {"lower": round(lower, 4), "upper": round(upper, 4)},
            "outlier_count": outlier_count,
            "total_count": count,
            "outlier_pct": round(outlier_count / count * 100, 2) if count else 0.0,
            "outlier_rows": _rows_to_records(frame),
        },
        evidence=_evidence(
            dataset,
            column=args.column,
            method=args.method,
            threshold=args.threshold,
            bounds={"lower": round(lower, 4), "upper": round(upper, 4)},
            outlier_count=outlier_count,
            value_count=count,
        ),
    )


@register_tool(
    "compute_correlations",
    description="Compute Pearson, Spearman or Kendall correlations between numeric columns.",
    input_model=ComputeCorrelationsInput,
    category="statistics",
    output_description="Pairwise correlation coefficients, strongest first.",
)
def tool_compute_correlations(ctx: ToolContext, args: ComputeCorrelationsInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    unknown = [c for c in args.columns if c not in allowed]
    if unknown:
        raise ValidationError(
            f"columns not found in the dataset: {', '.join(unknown[:10])}",
            details={"available_columns": allowed[:50]},
        )

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)
    select_list = ", ".join(
        f"CAST({quote_identifier(c, allowed)} AS DOUBLE) AS {quote_identifier(c)}" for c in args.columns
    )
    sql = f"SELECT {select_list} FROM {source}"
    if where:
        sql += f" WHERE {where}"
    frame = execute_dataframe(sql, params)
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if len(numeric) < 5:
        raise ValidationError(
            f"at least 5 rows with numeric values are required for correlation, found {len(numeric)}"
        )
    matrix = numeric.corr(method=args.method)

    pairs: list[dict[str, Any]] = []
    for i, first in enumerate(matrix.columns):
        for j, second in enumerate(matrix.columns):
            if j <= i:
                continue
            value = matrix.iloc[i, j]
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            if abs(float(value)) < args.min_abs:
                continue
            pairs.append(
                {
                    "x": str(first),
                    "y": str(second),
                    "correlation": round(float(value), 4),
                    "strength": _correlation_strength(float(value)),
                }
            )
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "columns": args.columns,
            "method": args.method,
            "pairs": pairs,
            "row_count": int(len(numeric)),
        },
        evidence=_evidence(dataset, columns=args.columns, method=args.method, row_count=int(len(numeric))),
    )


def _correlation_strength(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 0.8:
        return "strong"
    if magnitude >= 0.5:
        return "moderate"
    if magnitude >= 0.2:
        return "weak"
    return "negligible"


@register_tool(
    "compute_distribution",
    description="Summarise the distribution of a numeric column as histogram bins with counts and percentages.",
    input_model=ComputeDistributionInput,
    category="statistics",
    output_description="Histogram bins with lower/upper bounds, counts and percentages plus summary statistics.",
)
def tool_compute_distribution(ctx: ToolContext, args: ComputeDistributionInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    if args.column not in allowed:
        raise ValidationError(
            f"column '{args.column}' does not exist in this dataset",
            details={"available_columns": allowed[:50]},
        )

    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)
    ident = quote_identifier(args.column, allowed)
    sql = f"SELECT CAST({ident} AS DOUBLE) AS value FROM {source}"
    if where:
        sql += f" WHERE {where}"
    frame = execute_dataframe(sql, params)
    values = pd.to_numeric(frame["value"], errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < 2:
        raise ValidationError("not enough numeric values to build a distribution")

    counts, edges = np.histogram(values, bins=int(args.bins))
    total = int(counts.sum())
    buckets = []
    for index, count in enumerate(counts):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        buckets.append(
            {
                "bucket": f"{lower:.2f} – {upper:.2f}",
                "lower": round(lower, 4),
                "upper": round(upper, 4),
                "count": int(count),
                "pct": round(int(count) / total * 100, 2) if total else 0.0,
            }
        )

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "column": args.column,
            "bins": int(args.bins),
            "buckets": buckets,
            "summary": {
                "count": total,
                "mean": round(float(np.mean(values)), 4),
                "median": round(float(np.median(values)), 4),
                "std": round(float(np.std(values)), 4),
                "min": round(float(np.min(values)), 4),
                "max": round(float(np.max(values)), 4),
            },
        },
        evidence=_evidence(dataset, column=args.column, bins=int(args.bins), value_count=total),
    )


# --------------------------------------------------------------------------- #
# Joins
# --------------------------------------------------------------------------- #


@register_tool(
    "join_approved_datasets",
    description=(
        "Join two datasets on a user-approved key. The join must have been approved by the user "
        "for this request; otherwise the call is rejected."
    ),
    input_model=JoinApprovedDatasetsInput,
    category="join",
    output_description="Row counts of both inputs, the size of the join result and a bounded preview.",
)
def tool_join_approved_datasets(ctx: ToolContext, args: JoinApprovedDatasetsInput) -> ToolOutcome:
    ctx.authorize(args.left_dataset_id, args.right_dataset_id)
    approval = _find_approved_join(ctx, args)
    if approval is None:
        raise SecurityError(
            "this join has not been approved by the user. Approve the join key in the workspace first.",
            details={
                "left_dataset_id": args.left_dataset_id,
                "right_dataset_id": args.right_dataset_id,
                "left_key": args.left_key,
                "right_key": args.right_key,
            },
        )

    left = store.get_dataset(ctx.db, args.left_dataset_id)
    right = store.get_dataset(ctx.db, args.right_dataset_id)
    left_allowed = _column_names(left)
    right_allowed = _column_names(right)

    for column, allowed, side in (
        (args.left_key, left_allowed, "left"),
        (args.right_key, right_allowed, "right"),
    ):
        if column not in allowed:
            raise ValidationError(
                f"{side} join key '{column}' does not exist in that dataset",
                details={"available_columns": allowed[:50]},
            )

    left_columns = args.left_columns or list(left_allowed)
    right_columns = args.right_columns or list(right_allowed)
    for column in left_columns:
        if column not in left_allowed:
            raise ValidationError(f"left column '{column}' does not exist in the left dataset")
    for column in right_columns:
        if column not in right_allowed:
            raise ValidationError(f"right column '{column}' does not exist in the right dataset")

    left_select = list(dict.fromkeys([*left_columns, args.left_key]))
    right_select = list(dict.fromkeys([*right_columns, args.right_key]))

    left_source, left_params = source_clause(store.artifact_for(left))
    right_source, right_params = source_clause(store.artifact_for(right))

    left_ident = ", ".join(f"l.{quote_identifier(c, left_allowed)}" for c in left_select)
    collisions = set(left_select) & set(right_select)
    right_ident = ", ".join(
        f'r.{quote_identifier(c, right_allowed)} AS {quote_identifier(c + "__right")}'
        if c in collisions
        else f"r.{quote_identifier(c, right_allowed)}"
        for c in right_select
    )

    join_type = {
        "inner": "INNER JOIN",
        "left": "LEFT JOIN",
        "right": "RIGHT JOIN",
        "full": "FULL JOIN",
    }[args.how]
    sql = (
        f"SELECT {left_ident}, {right_ident} FROM {left_source} l "
        f"{join_type} {right_source} r ON l.{quote_identifier(args.left_key, left_allowed)} = "
        f"r.{quote_identifier(args.right_key, right_allowed)} "
        f"LIMIT {int(args.limit)}"
    )
    params = [*left_params, *right_params]
    frame = execute_dataframe(sql, params)

    count_sql = (
        f"SELECT COUNT(*) FROM {left_source} l {join_type} {right_source} r "
        f"ON l.{quote_identifier(args.left_key, left_allowed)} = r.{quote_identifier(args.right_key, right_allowed)}"
    )
    result_rows = _count_rows(count_sql, params)

    return ToolOutcome(
        data={
            "left_dataset_id": left.id,
            "right_dataset_id": right.id,
            "left_key": args.left_key,
            "right_key": args.right_key,
            "how": args.how,
            "left_rows": left.row_count,
            "right_rows": right.row_count,
            "result_rows": result_rows,
            "columns": [str(c) for c in frame.columns],
            "preview": _rows_to_records(frame),
        },
        evidence=_evidence(
            left,
            right_dataset_id=right.id,
            right_hash=right.source_hash,
            join_keys=[args.left_key, args.right_key],
            join_type=args.how,
            result_rows=result_rows,
            approved_join_id=approval.get("id"),
        ),
    )


def _find_approved_join(ctx: ToolContext, args: JoinApprovedDatasetsInput) -> dict[str, Any] | None:
    for join in ctx.approved_joins:
        left = join.get("left_dataset_id")
        right = join.get("right_dataset_id")
        left_key = join.get("left_key")
        right_key = join.get("right_key")
        if (
            left == args.left_dataset_id
            and right == args.right_dataset_id
            and left_key == args.left_key
            and right_key == args.right_key
        ):
            return join
        if (
            left == args.right_dataset_id
            and right == args.left_dataset_id
            and left_key == args.right_key
            and right_key == args.left_key
        ):
            return join
    statement = select(ApprovedJoin).where(
        ApprovedJoin.is_approved.is_(True),
        ApprovedJoin.left_dataset_id == args.left_dataset_id,
        ApprovedJoin.right_dataset_id == args.right_dataset_id,
    )
    for row in ctx.db.execute(statement).scalars().all():
        if row.left_key == args.left_key and row.right_key == args.right_key:
            return {
                "id": row.id,
                "left_dataset_id": row.left_dataset_id,
                "right_dataset_id": row.right_dataset_id,
                "left_key": row.left_key,
                "right_key": row.right_key,
            }
    return None


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #


@register_tool(
    "generate_chart",
    description=(
        "Build a validated chart specification (bar, column, line, area, pie, donut, scatter, histogram, heatmap, table). "
        "Charts are declarative - no code is executed."
    ),
    input_model=GenerateChartInput,
    category="presentation",
    requires_dataset=False,
    output_description="A declarative chart specification with sanitised labels and bounded data.",
)
def tool_generate_chart(ctx: ToolContext, args: GenerateChartInput) -> ToolOutcome:
    if not args.dataset_id:
        raise ValidationError("generate_chart requires a dataset_id")
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)

    if args.chart_type.value == "histogram":
        if not args.x or args.x not in allowed:
            raise ValidationError("a histogram requires a numeric column in 'x'")
        ident = quote_identifier(args.x, allowed)
        sql = f"SELECT CAST({ident} AS DOUBLE) AS value FROM {source}"
        if where:
            sql += f" WHERE {where}"
        frame = execute_dataframe(sql, params)
        values = pd.to_numeric(frame["value"], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values) < 2:
            raise ValidationError("not enough numeric values to build a histogram")
        counts, edges = np.histogram(values, bins=min(30, max(5, int(np.sqrt(len(values))))))
        histogram_data = [
            {"x": f"{edges[i]:.2f} – {edges[i + 1]:.2f}", "y": int(count)} for i, count in enumerate(counts)
        ]
        spec = {
            "chart_type": "bar",
            "title": args.title or f"Distribution of {args.x}",
            "x_key": "x",
            "data": histogram_data,
            "x_label": args.x,
            "y_label": "Rows",
            "evidence": _evidence(dataset, column=args.x),
        }
        return ToolOutcome(
            data={"chart_spec": validate_chart_spec(spec), "row_count": len(histogram_data)},
            chart=validate_chart_spec(spec),
            evidence=_evidence(dataset),
        )

    if not args.x or args.x not in allowed:
        raise ValidationError("the chart needs an existing column for 'x'")
    y_columns = [c for c in (args.y or []) if c]
    for column in y_columns:
        if column not in allowed:
            raise ValidationError(f"chart column '{column}' does not exist in this dataset")
    if not y_columns:
        raise ValidationError("the chart needs at least one column in 'y'")

    group_expr = None
    if args.group_by:
        if args.group_by not in allowed:
            raise ValidationError(f"chart group column '{args.group_by}' does not exist in this dataset")
        group_expr = quote_identifier(args.group_by, allowed)

    bucket = args.bucket
    if bucket:
        bucket_expr = _bucket_expression(bucket, quote_identifier(args.x, allowed))
    else:
        bucket_expr = quote_identifier(args.x, allowed)

    group_parts = [bucket_expr]
    select_parts = [f"{bucket_expr} AS {quote_identifier('x')}"]
    if group_expr:
        select_parts.append(f"{group_expr} AS {quote_identifier('series')}")
        group_parts.append(group_expr)

    aggregation = args.aggregation.value if args.aggregation else "sum"
    for column in y_columns:
        ident = quote_identifier(column, allowed)
        expr = (
            f"CAST({ident} AS DECIMAL(18,4))"
            if aggregation in {"sum", "mean", "median", "min", "max"}
            else ident
        )
        select_parts.append(f"{agg_expression(aggregation, expr)} AS {quote_identifier(column)}")

    sql = f"SELECT {', '.join(select_parts)} FROM {source}"
    if where:
        sql += f" WHERE {where}"
    sql += f" GROUP BY {', '.join(group_parts)}"
    if bucket:
        # Time buckets are always ordered chronologically.
        sql += f" ORDER BY {bucket_expr} ASC"
    elif args.sort_by and args.sort_by in allowed:
        direction = "DESC" if args.sort_dir.value == "desc" else "ASC"
        sql += f" ORDER BY {quote_identifier(args.sort_by, allowed)} {direction} NULLS LAST"
    sql += f" LIMIT {int(args.limit)}"

    frame = execute_dataframe(sql, params)
    records = _rows_to_records(frame)
    data: list[dict[str, Any]] = []
    for record in records:
        point: dict[str, Any] = {"x": sanitize_text(record.get("x"))}
        if group_expr:
            point["series"] = sanitize_text(record.get("series"))
        for column in y_columns:
            value = record.get(column)
            point[column] = None if value is None else float(value)
        data.append(point)

    if args.chart_type.value in {"pie", "donut"} and len(data) > 50:
        data = data[:50]

    spec = {
        "chart_type": args.chart_type.value,
        "title": args.title or f"{aggregation.title()} of {', '.join(y_columns)} by {args.x}",
        "x_key": "x",
        "data": data,
        "x_label": args.x,
        "y_label": ", ".join(y_columns),
        "currency": args.currency,
        "evidence": _evidence(dataset, aggregation=aggregation, bucket=bucket),
    }
    validated = validate_chart_spec(spec)
    return ToolOutcome(
        data={"chart_spec": validated, "row_count": len(data)},
        chart=validated,
        evidence=_evidence(dataset, aggregation=aggregation, point_count=len(data)),
    )


@register_tool(
    "export_results",
    description=(
        "Export dataset rows (optionally filtered) as sanitised CSV, XLSX or JSON. "
        "Spreadsheet formula injection is neutralised."
    ),
    input_model=ExportResultsInput,
    category="presentation",
    output_description="The exported rows, the target format and a download descriptor.",
)
def tool_export_results(ctx: ToolContext, args: ExportResultsInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    allowed = _column_names(dataset)
    source, source_params = source_clause(_artifact(dataset))
    params = list(source_params)
    where = build_where(args.filters, allowed, params)

    select_list = "*"
    if args.columns:
        unknown = [c for c in args.columns if c not in allowed]
        if unknown:
            raise ValidationError(f"columns not found: {', '.join(unknown[:10])}")
        select_list = ", ".join(quote_identifier(c, allowed) for c in args.columns)

    sql = f"SELECT {select_list} FROM {source}"
    if where:
        sql += f" WHERE {where}"
    if args.sort_by:
        if args.sort_by not in allowed:
            raise ValidationError(f"sort column '{args.sort_by}' does not exist in this dataset")
        direction = "DESC" if args.sort_dir.value == "desc" else "ASC"
        sql += f" ORDER BY {quote_identifier(args.sort_by, allowed)} {direction} NULLS LAST"
    sql += f" LIMIT {int(args.limit)}"
    frame = execute_dataframe(sql, params)

    sanitized = frame.copy()
    for column in sanitized.columns:
        sanitized[column] = sanitized[column].map(sanitize_export_cell)
    records = _rows_to_records(sanitized)

    export_id = uuid.uuid4().hex[:12]
    filename = f"{dataset.name.replace(' ', '_').lower()}_{export_id}.{args.format}"
    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "format": args.format,
            "row_count": len(records),
            "columns": [str(c) for c in frame.columns],
            "rows": records,
            "export_id": export_id,
            "filename": filename,
        },
        export={
            "export_id": export_id,
            "format": args.format,
            "filename": filename,
            "row_count": len(records),
        },
        evidence=_evidence(
            dataset,
            format=args.format,
            exported_rows=len(records),
            filters=[f.model_dump(mode="json") for f in (args.filters or [])],
            sanitised="spreadsheet formula injection neutralised",
        ),
    )


@register_tool(
    "explain_calculation",
    description="Explain the definition, formula and required columns of a calculation or KPI.",
    input_model=ExplainCalculationInput,
    category="kpi",
    output_description="The formal definition, formula, required roles and the columns that would be used.",
)
def tool_explain_calculation(ctx: ToolContext, args: ExplainCalculationInput) -> ToolOutcome:
    dataset = _dataset(ctx, args.dataset_id)
    columns = _columns(dataset)
    key = args.calculation.strip().lower().replace(" ", "_")
    definition = KPI_CATALOGUE.get(key)

    if definition is None:
        return ToolOutcome(
            data={
                "dataset_id": dataset.id,
                "calculation": args.calculation,
                "definition": "This is a custom calculation described by the tool arguments.",
                "formula": "See the tool trace for the exact query parameters that were used.",
                "params": args.params,
                "dataset_columns": [str(c["name"]) for c in columns],
            },
            evidence=_evidence(dataset),
        )

    resolved: dict[str, Any] = {}
    for role in definition.required_roles:
        column, resolution = resolve_role(role, columns, param_for_role(args.params, role))
        resolved[role] = {"column": column, "resolution": resolution}

    return ToolOutcome(
        data={
            "dataset_id": dataset.id,
            "calculation": definition.name,
            "label": definition.label,
            "definition": definition.description,
            "formula": definition.formula,
            "unit": definition.unit,
            "required_roles": list(definition.required_roles),
            "column_resolution": resolved,
            "params": args.params,
            "dataset_columns": [str(c["name"]) for c in columns],
            "notes": definition.notes,
        },
        evidence=_evidence(dataset, calculation=definition.name, formula=definition.formula),
    )
