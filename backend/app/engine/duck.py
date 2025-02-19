"""DuckDB execution layer.

All analytical work is expressed as SQL that is *assembled server side from
trusted templates*.  Two rules are enforced by this module:

1.  Values are always passed as bound parameters (``?`` placeholders).  The
    model can therefore never inject SQL through a filter value.
2.  Identifiers (column names) are validated against the allowlist of the
    dataset's own schema and then double-quoted.  A column name that is not
    part of the dataset is rejected before the query is built.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from ..core.errors import SecurityError, ValidationError
from ..core.security import is_safe_identifier

_write_lock = threading.RLock()
_connection: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared in-memory DuckDB connection.

    A single connection is reused for the lifetime of the process.  All
    queries are serialised with ``_write_lock`` which is safe for a local,
    single-user application and avoids the cost of re-opening the database
    for every tool call.
    """
    global _connection
    if _connection is None:
        _connection = duckdb.connect(database=":memory:")
    return _connection


def close_connection() -> None:
    global _connection
    if _connection is not None:
        with _write_lock:
            _connection.close()
        _connection = None


def quote_identifier(name: str, allowed: Iterable[str] | None = None) -> str:
    """Validate and quote an SQL identifier.

    ``allowed`` is the set of column names that exist in the dataset.  When
    provided, anything outside that set is rejected - this is what stops a
    model from referencing columns of a different dataset.
    """
    if not isinstance(name, str) or not name:
        raise SecurityError(f"invalid identifier: {name!r}")
    if not is_safe_identifier(name):
        raise SecurityError(f"unsafe identifier rejected: {name!r}")
    if allowed is not None and name not in set(allowed):
        raise ValidationError(
            f"column '{name}' does not exist in this dataset",
            details={"available_columns": sorted(allowed)[:50]},
        )
    return '"' + name.replace('"', '""') + '"'


@dataclass
class Query:
    """A SQL statement plus its bound parameters."""

    sql: str
    params: list[Any]

    def execute(self) -> pd.DataFrame:
        return execute_dataframe(self.sql, self.params)

    def scalar(self) -> Any:
        rows = execute_dataframe(self.sql, self.params)
        if rows.empty:
            return None
        return rows.iloc[0, 0]


def execute_dataframe(sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
    """Run a query and return the result as a DataFrame."""
    conn = get_connection()
    with _write_lock:
        try:
            return conn.execute(sql, list(params or [])).fetch_df()
        except duckdb.Error as exc:  # pragma: no cover - defensive
            raise ValidationError(f"query execution failed: {str(exc)[:300]}") from exc


def execute_scalar(sql: str, params: Sequence[Any] | None = None) -> Any:
    conn = get_connection()
    with _write_lock:
        row = conn.execute(sql, list(params or [])).fetchone()
    return row[0] if row else None


def source_clause(artifact_path: str) -> tuple[str, list[Any]]:
    """``FROM read_parquet(?)`` fragment for a normalised artifact."""
    if not artifact_path:
        raise ValidationError("dataset artifact is missing")
    return "read_parquet(?)", [artifact_path]


def build_where(
    filters: Sequence[Any] | None,
    allowed_columns: Iterable[str],
    params: list[Any],
) -> str:
    """Translate validated filter specs into a parameterised WHERE clause.

    Only operators with a clear SQL semantics are supported; string matching
    uses ``ILIKE`` with escaped wildcards so that ``%`` in user data cannot
    widen the predicate.
    """
    if not filters:
        return ""
    allowed = set(allowed_columns)
    clauses: list[str] = []
    for spec in filters:
        column = spec.column
        if column not in allowed:
            raise ValidationError(
                f"filter column '{column}' does not exist in this dataset",
                details={"available_columns": sorted(allowed)[:50]},
            )
        ident = quote_identifier(column)
        op = spec.op.value if hasattr(spec.op, "value") else str(spec.op)
        value = spec.value
        if op == "eq":
            clauses.append(f"{ident} = ?")
            params.append(value)
        elif op == "neq":
            clauses.append(f"{ident} IS DISTINCT FROM ?")
            params.append(value)
        elif op == "gt":
            clauses.append(f"{ident} > ?")
            params.append(value)
        elif op == "gte":
            clauses.append(f"{ident} >= ?")
            params.append(value)
        elif op == "lt":
            clauses.append(f"{ident} < ?")
            params.append(value)
        elif op == "lte":
            clauses.append(f"{ident} <= ?")
            params.append(value)
        elif op == "between":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValidationError("`between` requires a [low, high] list")
            clauses.append(f"{ident} BETWEEN ? AND ?")
            params.extend([value[0], value[1]])
        elif op == "in":
            if not isinstance(value, (list, tuple)) or not value:
                raise ValidationError("`in` requires a non-empty list")
            placeholders = ", ".join("?" for _ in value)
            clauses.append(f"{ident} IN ({placeholders})")
            params.extend(list(value))
        elif op == "contains":
            escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(f"{ident} ILIKE ?")
            params.append(f"%{escaped}%")
        elif op == "startswith":
            escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(f"{ident} ILIKE ?")
            params.append(f"{escaped}%")
        elif op == "is_null":
            clauses.append(f"{ident} IS NULL")
        elif op == "not_null":
            clauses.append(f"{ident} IS NOT NULL")
        else:  # pragma: no cover - guarded by the enum
            raise ValidationError(f"unsupported filter operator: {op}")
    return " AND ".join(clauses)


#: SQL expressions for each supported aggregation.
AGG_EXPRESSIONS: dict[str, str] = {
    "sum": "SUM({expr})",
    "mean": "AVG({expr})",
    "median": "MEDIAN({expr})",
    "min": "MIN({expr})",
    "max": "MAX({expr})",
    "count": "COUNT({expr})",
    "count_distinct": "COUNT(DISTINCT {expr})",
    "n_unique": "COUNT(DISTINCT {expr})",
    "std": "STDDEV_POP({expr})",
    "var": "VAR_POP({expr})",
    "first": "FIRST({expr})",
    "last": "LAST({expr})",
}


def agg_expression(agg: str, expr: str) -> str:
    template = AGG_EXPRESSIONS.get(agg)
    if template is None:
        raise ValidationError(f"unsupported aggregation: {agg}")
    return template.format(expr=expr)


def decimal_cast(identifier: str) -> str:
    """Cast to DECIMAL so that monetary sums are exact."""
    return f"CAST({identifier} AS DECIMAL(18,4))"


def build_grouped_aggregate(
    *,
    artifact_path: str,
    group_by: Sequence[str],
    metrics: Sequence[Any],
    filters: Sequence[Any] | None,
    allowed_columns: Iterable[str],
    order_by: str | None = None,
    order_dir: str = "desc",
    limit: int | None = None,
) -> Query:
    """Build a grouped aggregation query from a trusted template."""
    allowed = set(allowed_columns)
    params: list[Any] = []
    group_exprs: list[str] = []
    for column in group_by:
        if column not in allowed:
            raise ValidationError(f"group column '{column}' does not exist in this dataset")
        group_exprs.append(quote_identifier(column))

    select_parts: list[str] = []
    for column in group_by:
        ident = quote_identifier(column)
        select_parts.append(f"{ident} AS {quote_identifier(column)}")

    for metric in metrics:
        agg = metric.agg.value if hasattr(metric.agg, "value") else str(metric.agg)
        alias = metric.alias or f"{metric.column or 'rows'}_{agg}"
        if agg == "count" and not metric.column:
            select_parts.append(f"COUNT(*) AS {quote_identifier(alias)}")
            continue
        if not metric.column:
            raise ValidationError(f"aggregation '{agg}' requires a column")
        if metric.column not in allowed:
            raise ValidationError(
                f"metric column '{metric.column}' does not exist in this dataset",
                details={"available_columns": sorted(allowed)[:50]},
            )
        ident = quote_identifier(metric.column)
        expr = decimal_cast(ident) if agg in {"sum", "mean", "median", "min", "max"} else ident
        select_parts.append(f"{agg_expression(agg, expr)} AS {quote_identifier(alias)}")

    source, source_params = source_clause(artifact_path)
    params.extend(source_params)

    sql = f"SELECT {', '.join(select_parts)} FROM {source}"
    where = build_where(filters, allowed, params)
    if where:
        sql += f" WHERE {where}"
    if group_exprs:
        sql += f" GROUP BY {', '.join(group_exprs)}"
    aliases = {
        (m.alias or f"{m.column or 'rows'}_{m.agg.value if hasattr(m.agg, 'value') else m.agg}")
        for m in metrics
    }
    if order_by and (order_by in allowed or order_by in aliases):
        direction = "DESC" if order_dir == "desc" else "ASC"
        sql += f" ORDER BY {quote_identifier(order_by, allowed | aliases)} {direction} NULLS LAST"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return Query(sql=sql, params=params)


def build_single_aggregate(
    *,
    artifact_path: str,
    metrics: Sequence[Any],
    filters: Sequence[Any] | None,
    allowed_columns: Iterable[str],
) -> Query:
    """Build a whole-dataset aggregation query from a trusted template."""
    allowed = set(allowed_columns)
    params: list[Any] = []
    select_parts: list[str] = []
    for metric in metrics:
        agg = metric.agg.value if hasattr(metric.agg, "value") else str(metric.agg)
        alias = metric.alias or f"{metric.column or 'rows'}_{agg}"
        if agg == "count" and not metric.column:
            select_parts.append(f"COUNT(*) AS {quote_identifier(alias)}")
            continue
        if not metric.column:
            raise ValidationError(f"aggregation '{agg}' requires a column")
        if metric.column not in allowed:
            raise ValidationError(
                f"metric column '{metric.column}' does not exist in this dataset",
                details={"available_columns": sorted(allowed)[:50]},
            )
        ident = quote_identifier(metric.column)
        expr = decimal_cast(ident) if agg in {"sum", "mean", "median", "min", "max"} else ident
        select_parts.append(f"{agg_expression(agg, expr)} AS {quote_identifier(alias)}")

    source, source_params = source_clause(artifact_path)
    params.extend(source_params)
    sql = f"SELECT {', '.join(select_parts)} FROM {source}"
    where = build_where(filters, allowed, params)
    if where:
        sql += f" WHERE {where}"
    return Query(sql=sql, params=params)
