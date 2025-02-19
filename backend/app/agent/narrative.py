"""Deterministic answer synthesis.

The narrative is built *from the tool outputs* - never from model memory.
Every number that appears here comes from a tool result, so the answer is
grounded by construction.  When a language model is used, its text replaces
this narrative but is then verified against the same observations.
"""

from __future__ import annotations

from typing import Any

from ..core.money import format_money


def _fmt_number(value: Any, currency: str | None = None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if currency:
            return format_money(value, currency)
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value)


def _percent(value: Any) -> str:
    if value is None:
        return "undefined"
    return f"{float(value):,.2f}%"


def build_narrative(
    question: str,
    tool_trace: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
    *,
    clarification: str | None = None,
    currency: str = "USD",
) -> str:
    """Compose the evidence-backed answer from the tool trace."""
    lines: list[str] = []
    lines.append(f"**Question:** {question}")
    lines.append("")

    successful = [t for t in tool_trace if t.get("status") == "success"]
    failed = [t for t in tool_trace if t.get("status") != "success"]

    if clarification:
        lines.append("### Clarification needed")
        lines.append(clarification)
        lines.append("")

    if not successful:
        lines.append("### Result")
        lines.append(
            "I could not answer this question with the data that is available. "
            "No analysis tool completed successfully."
        )
    else:
        for step in successful:
            section = _summarise_tool(step, currency)
            if section:
                lines.extend(section)
                lines.append("")

    lines.extend(_dataset_section(datasets))

    if successful:
        lines.append("### Method")
        lines.append(f"- Tools executed: {', '.join(step.get('tool', '?') for step in successful)}")
        lines.append("- Every figure above was produced by the tools listed in the execution trace.")
        lines.append(
            "- Open **How this was calculated** for formulas, filters, row counts and period boundaries."
        )
        lines.append("")

    if failed:
        lines.append("### Caveats")
        for step in failed:
            lines.append(f"- Tool `{step.get('tool')}` failed: {step.get('error', 'unknown error')}")
        lines.append("")

    lines.append(
        "*This answer reports computed facts. Interpretation and recommendations are labelled separately "
        "and are not part of the verified evidence.*"
    )
    return "\n".join(lines).strip()


def _dataset_section(datasets: list[dict[str, Any]]) -> list[str]:
    if not datasets:
        return []
    lines = ["### Evidence"]
    for dataset in datasets:
        parts = [
            f"**{dataset.get('name', 'dataset')}**",
            f"id `{str(dataset.get('id'))[:8]}`",
            f"v{dataset.get('version', 1)}",
            f"{dataset.get('row_count', 0):,} rows",
            f"{dataset.get('column_count', 0)} columns",
        ]
        if dataset.get("sheet"):
            parts.append(f"sheet `{dataset['sheet']}`")
        if dataset.get("file_hash"):
            parts.append(f"sha256 `{dataset['file_hash'][:12]}`")
        lines.append("- " + " · ".join(parts))
    return lines


def _summarise_tool(step: dict[str, Any], currency: str) -> list[str]:
    tool = step.get("tool")
    data = (step.get("output") or {}).get("data", {}) or {}
    handler = _HANDLERS.get(tool)
    if handler is None:
        return []
    return handler(data, step, currency)


def _kpi_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    groups = data.get("groups")
    if groups:
        lines = [
            "### Result",
            f"**{data.get('label', 'KPI')} by {', '.join(data.get('grouped_by') or [])}**",
        ]
        for entry in groups[:20]:
            lines.append(f"- {entry.get('group')}: {entry.get('display_value')}")
        resolution = data.get("column_resolution") or {}
        if resolution:
            used = ", ".join(
                f"`{info.get('column')}` ({info.get('resolution')})"
                for info in resolution.values()
                if info.get("column")
            )
            if used:
                lines.append(f"- Columns used: {used}")
        if data.get("notes"):
            lines.append(f"- Note: {data['notes']}")
        return lines
    value = data.get("value")
    unit = data.get("unit", "")
    label = data.get("label") or data.get("kpi", "KPI")
    if unit == "currency":
        rendered = format_money(value, data.get("currency") or currency)
    elif unit == "percent":
        rendered = _percent(value)
    else:
        rendered = _fmt_number(value)
    lines = ["### Result", f"**{label}: {rendered}**"]
    details = data.get("details") or {}
    for key, item in details.items():
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            lines.append(
                f"- {key.replace('_', ' ')}: {_fmt_number(item, currency if 'value' in key else None)}"
            )
    resolution = data.get("column_resolution") or {}
    if resolution:
        used = ", ".join(
            f"`{info.get('column')}` ({info.get('resolution')})"
            for info in resolution.values()
            if info.get("column")
        )
        if used:
            lines.append(f"- Columns used: {used}")
    return lines


def _timeseries_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    periods = data.get("periods") or []
    if not periods:
        return []
    metric_keys = [
        key
        for key in periods[0]
        if key not in {"period", "previous_value", "change", "growth_pct", "growth_note"}
    ]
    lines = ["### Result", f"**{len(periods)} {data.get('bucket', 'period')} buckets**"]
    for record in periods:
        pieces = [str(record.get("period"))]
        for key in metric_keys:
            pieces.append(f"{key}={_fmt_number(record.get(key), currency)}")
        if record.get("growth_pct") is not None:
            pieces.append(f"growth={_percent(record.get('growth_pct'))}")
        elif record.get("growth_note"):
            pieces.append("growth undefined")
        lines.append("- " + ", ".join(pieces))
    return lines


def _ranking_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    ranked = data.get("ranked") or data.get("top") or []
    if not ranked:
        return []
    lines = [
        "### Result",
        f"**Top {len(ranked)} {data.get('category_column', 'category')} by {data.get('metric_column', 'metric')}**",
    ]
    for entry in ranked:
        share = f" ({entry['share_pct']:.2f}% of total)" if entry.get("share_pct") is not None else ""
        lines.append(f"- {entry.get('category')}: {_fmt_number(entry.get('value'), currency)}{share}")
    if data.get("total") is not None:
        lines.append(f"- Total: {_fmt_number(data.get('total'), currency)}")
    return lines


def _period_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    p1 = data.get("period1") or {}
    p2 = data.get("period2") or {}
    lines = [
        "### Result",
        f"**{data.get('metric', 'metric')}**",
        f"- Period 1 ({p1.get('start')} → {p1.get('end')}): {_fmt_number(p1.get('value'), currency)}",
        f"- Period 2 ({p2.get('start')} → {p2.get('end')}): {_fmt_number(p2.get('value'), currency)}",
        f"- Change: {_fmt_number(data.get('absolute_change'), currency)} ({_percent(data.get('percent_change'))})",
    ]
    comparisons = data.get("comparisons") or []
    if comparisons:
        lines.append("")
        lines.append("By group:")
        for entry in comparisons[:20]:
            lines.append(
                f"- {entry.get('group')}: {_fmt_number(entry.get('period1_value'), currency)} → "
                f"{_fmt_number(entry.get('period2_value'), currency)} ({_percent(entry.get('percent_change'))})"
            )
    return lines


def _quality_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    score = data.get("score")
    lines = ["### Result", f"**Data-quality score: {score}/100**"]
    duplicates = data.get("duplicates") or {}
    lines.append(f"- Duplicate rows: {duplicates.get('count', 0)} ({duplicates.get('pct', 0)}%)")
    missing = {
        name: value for name, value in (data.get("missing_values") or {}).items() if value.get("missing")
    }
    if missing:
        top = sorted(missing.items(), key=lambda item: item[1].get("pct", 0), reverse=True)[:8]
        lines.append(
            "- Columns with missing values: "
            + ", ".join(f"`{name}` ({value.get('pct')}%)" for name, value in top)
        )
    for warning in (data.get("warnings") or [])[:5]:
        lines.append(f"- {warning}")
    return lines


def _correlation_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    pairs = data.get("pairs") or []
    if not pairs:
        return []
    lines = ["### Result", f"**{len(pairs)} correlated pairs ({data.get('method')})**"]
    for pair in pairs[:10]:
        lines.append(
            f"- `{pair.get('x')}` ↔ `{pair.get('y')}`: r = {pair.get('correlation')} ({pair.get('strength')})"
        )
    return lines


def _outlier_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    bounds = data.get("bounds") or {}
    return [
        "### Result",
        f"**{data.get('outlier_count', 0)} outliers in `{data.get('column')}` "
        f"({data.get('outlier_pct', 0)}% of {data.get('total_count', 0)} values)**",
        f"- Method: {data.get('method')} (threshold {data.get('threshold')}), "
        f"bounds [{_fmt_number(bounds.get('lower'))}, {_fmt_number(bounds.get('upper'))}]",
    ]


def _distribution_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    buckets = data.get("buckets") or []
    summary = data.get("summary") or {}
    if not buckets:
        return []
    lines = [
        "### Result",
        f"**Distribution of `{data.get('column')}` across {len(buckets)} bins**",
        f"- mean {summary.get('mean')}, median {summary.get('median')}, "
        f"min {summary.get('min')}, max {summary.get('max')}",
    ]
    for bucket in buckets:
        lines.append(f"- {bucket.get('bucket')}: {bucket.get('count')} ({bucket.get('pct')}%)")
    return lines


def _filter_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    filters = data.get("filters_applied") or []
    return [
        "### Result",
        f"**{data.get('filtered_row_count', 0):,} of {data.get('original_row_count', 0):,} rows match the filters**",
        "- Filters: "
        + (", ".join(f"`{f.get('column')} {f.get('op')} {f.get('value')}`" for f in filters) or "none"),
    ]


def _group_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    results = data.get("results") or []
    if not results:
        return []
    lines = ["### Result", f"**{len(results)} groups**"]
    for row in results[:20]:
        pieces = []
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                pieces.append(f"{key}={_fmt_number(value, currency)}")
            else:
                pieces.append(f"{key}={value}")
        lines.append("- " + ", ".join(pieces))
    return lines


def _join_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    return [
        "### Result",
        f"**{data.get('result_rows', 0):,} joined rows** "
        f"({data.get('how')} join on `{data.get('left_key')}` = `{data.get('right_key')}`)",
        f"- Left dataset rows: {data.get('left_rows', 0):,}",
        f"- Right dataset rows: {data.get('right_rows', 0):,}",
    ]


def _profile_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    summary = data.get("numeric_summary") or {}
    lines = ["### Result", f"**Descriptive statistics for {len(summary)} numeric columns**"]
    for name, stats in list(summary.items())[:10]:
        lines.append(
            f"- `{name}`: mean {_fmt_number(stats.get('mean'), currency)}, "
            f"median {_fmt_number(stats.get('median'), currency)}, "
            f"min {_fmt_number(stats.get('min'), currency)}, max {_fmt_number(stats.get('max'), currency)}"
        )
    return lines


def _export_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    return [
        "### Result",
        f"**Exported {data.get('row_count', 0):,} rows as {str(data.get('format', '')).upper()}**",
        f"- File: `{data.get('filename')}`",
        "- Cells are sanitised against spreadsheet formula injection.",
    ]


def _schema_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    columns = data.get("columns") or []
    lines = ["### Result", f"**{data.get('column_count', 0)} columns, {data.get('row_count', 0):,} rows**"]
    for column in columns[:40]:
        lines.append(
            f"- `{column.get('name')}` - {column.get('type')} (missing {column.get('missing_pct', 0)}%)"
        )
    return lines


def _preview_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    return [
        "### Result",
        f"**Showing {len(data.get('rows') or [])} of {data.get('total_rows', 0):,} rows**",
    ]


def _chart_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    spec = data.get("chart_spec") or {}
    return [
        "### Result",
        f"**{spec.get('chart_type', 'chart')} chart prepared: {spec.get('title', '')}**",
        f"- {data.get('row_count', 0)} data points",
    ]


def _explain_summary(data: dict[str, Any], step: dict[str, Any], currency: str) -> list[str]:
    lines = ["### Definition", str(data.get("definition", ""))]
    if data.get("formula"):
        lines.append(f"- Formula: `{data['formula']}`")
    resolution = data.get("column_resolution") or {}
    if resolution:
        used = ", ".join(
            f"`{info.get('column')}` ({info.get('resolution')})"
            for info in resolution.values()
            if info.get("column")
        )
        if used:
            lines.append(f"- Columns used: {used}")
    if data.get("notes"):
        lines.append(f"- Note: {data['notes']}")
    return lines


_HANDLERS = {
    "compute_kpi": _kpi_summary,
    "time_series": _timeseries_summary,
    "rank_categories": _ranking_summary,
    "compare_periods": _period_summary,
    "check_data_quality": _quality_summary,
    "compute_correlations": _correlation_summary,
    "detect_outliers": _outlier_summary,
    "compute_distribution": _distribution_summary,
    "apply_filters": _filter_summary,
    "group_by": _group_summary,
    "aggregate_metrics": _group_summary,
    "join_approved_datasets": _join_summary,
    "profile_data": _profile_summary,
    "export_results": _export_summary,
    "inspect_schema": _schema_summary,
    "preview_rows": _preview_summary,
    "generate_chart": _chart_summary,
    "explain_calculation": _explain_summary,
}


def build_how_calculated(
    tool_trace: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    provider: str,
    model: str | None,
) -> dict[str, Any]:
    """Assemble the transparent 'How this was calculated' panel."""
    steps: list[dict[str, Any]] = []
    for step in tool_trace:
        output = step.get("output") or {}
        data = output.get("data") or {}
        evidence = output.get("evidence") or {}
        steps.append(
            {
                "step": step.get("step"),
                "tool": step.get("tool"),
                "status": step.get("status"),
                "reason": step.get("reason"),
                "input": step.get("input"),
                "evidence": evidence,
                "row_counts": {
                    "dataset_rows": evidence.get("row_count"),
                    "filtered_rows": data.get("filtered_row_count"),
                    "result_rows": data.get("row_count"),
                },
                "filters": data.get("filters") or data.get("filters_applied") or [],
                "periods": {
                    "period1": data.get("period1"),
                    "period2": data.get("period2"),
                    "bucket": data.get("bucket"),
                },
                "formula": data.get("formula"),
                "elapsed_ms": (output.get("_meta") or {}).get("elapsed_ms"),
                "warnings": step.get("warnings") or [],
            }
        )

    return {
        "plan": plan,
        "steps": steps,
        "datasets": datasets,
        "provider": provider,
        "model": model,
        "definitions": {
            "percentage_change": "(new - old) / old * 100; undefined when the baseline is zero",
            "share_of_total": "group value / sum of all group values * 100",
            "outliers_iqr": "values outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]",
            "outliers_zscore": "|z| greater than the configured threshold",
            "correlation": "Pearson (linear) or Spearman (rank) on pairwise complete observations",
            "time_bucketing": "calendar buckets of the source dates; no timezone conversion is applied",
            "money": "sums are computed in DECIMAL(18,4) and rounded to 2 decimals for display",
        },
        "assumptions": [
            "Null values are excluded from numeric aggregations.",
            "Dates are read exactly as written in the source file; no timezone conversion is applied.",
            "Money columns are parsed with thousands separators and currency symbols removed.",
            "Duplicates are reported but never silently removed.",
            "Zero denominators produce an explicit 'undefined' rather than an infinite percentage.",
        ],
        "exclusions": [
            "Rows removed by an explicit filter.",
            "Null values in numeric aggregates.",
        ],
        "execution_metadata": {
            "tool_count": len(tool_trace),
            "successful_tools": sum(1 for s in tool_trace if s.get("status") == "success"),
            "provider": provider,
            "model": model,
        },
    }
