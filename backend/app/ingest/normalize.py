"""Schema inference, profiling and data-quality analysis.

The inference rules are intentionally conservative and *explainable*: every
column gets a declared type plus the reason it was chosen, so the UI can
show the user why a column is treated as currency or as a date.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

from ..core.money import CURRENCY_SYMBOLS, detect_currency, to_decimal
from ..core.periods import to_datetime_series
from ..core.security import looks_like_formula, scan_text_for_injection
from ..domain.kpis import ROLE_HINTS

_TRUE_VALUES = {"true", "yes", "y", "1", "t"}
_FALSE_VALUES = {"false", "no", "n", "0", "f"}

_CURRENCY_RE = re.compile(r"^[\s]*([$€£¥₹₽₩]|US\$|R\$|C\$|A\$)\s?-?[\d,]+(\.\d+)?\s*%?$")

_INJECTION_HEADER_RE = re.compile(
    r"(ignore\s+(all\s+)?previous|system\s+prompt|you\s+are\s+now|drop\s+table|"
    r"select\s+.*\s+from|exec\(|eval\(|__import__|rm\s+-rf)",
    re.IGNORECASE,
)


def _sample(series: pd.Series, n: int = 200) -> pd.Series:
    return series.dropna().head(n)


def infer_column_type(series: pd.Series) -> tuple[str, str]:
    """Return ``(inferred_type, reason)`` for a column."""
    sample = _sample(series)
    if sample.empty:
        return "empty", "no non-null values to inspect"

    if pd.api.types.is_bool_dtype(series):
        return "boolean", "native boolean dtype"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime", "native datetime dtype"

    if pd.api.types.is_numeric_dtype(series):
        return "numeric", f"native {series.dtype} dtype"

    text = sample.astype(str).str.strip()
    lowered = set(text.str.lower())

    if (
        lowered.issubset(_TRUE_VALUES | _FALSE_VALUES)
        and len(lowered) > 0
        and series.nunique(dropna=True) <= 2
    ):
        return "boolean", "values are exclusively true/false style tokens"

    currency_hits = sum(1 for v in text if _CURRENCY_RE.match(v))
    if currency_hits / len(text) >= 0.6:
        code = detect_currency(text.tolist())
        return "currency", f"values carry a currency symbol (detected {code})"

    numeric_hits = sum(1 for v in text if to_decimal(v) is not None)
    if numeric_hits / len(text) >= 0.95:
        return "numeric", "values parse as numbers"

    parsed = pd.to_datetime(text, errors="coerce", format="mixed")
    if parsed.notna().sum() / len(text) >= 0.9:
        return "date", "values parse as dates"

    if numeric_hits / len(text) >= 0.2:
        return "mixed_numeric", "some but not all values parse as numbers"

    return "string", "free-form text"


def role_for_column(name: str, inferred_type: str) -> str | None:
    """Suggest a semantic role for a column based on its name and type."""
    lowered = name.lower()
    for role, hints in ROLE_HINTS.items():
        for hint in hints:
            if hint == lowered:
                return role
    for role, hints in ROLE_HINTS.items():
        for hint in hints:
            if hint in lowered:
                if role == "money" and inferred_type not in {"numeric", "currency", "mixed_numeric"}:
                    continue
                if role == "date" and inferred_type not in {"date", "datetime"}:
                    continue
                return role
    return None


def _numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    return series.map(lambda v: to_decimal(v) if not isinstance(v, (int, float, np.number)) else v).astype(
        "float64"
    )


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (pd.Timedelta,)):
        return str(value)
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


def profile_frame(
    frame: pd.DataFrame,
    *,
    redact_samples: bool = True,
    raw_types: dict[str, str] | None = None,
    original: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build a per-column profile used by the schema viewer and the tools.

    ``raw_types`` and ``original`` describe the *original* (pre-coercion)
    frame.  They are used to keep the semantic type of a column intact: a
    column that was coerced from ``"$1,234.56"`` to a float is still reported
    as ``currency`` and not as a plain number.
    """
    row_count = int(len(frame))
    columns: list[dict[str, Any]] = []
    warnings: list[str] = []

    for position, name in enumerate(frame.columns):
        series = frame[name]
        inferred, reason = infer_column_type(series)
        original_type = (raw_types or {}).get(str(name))
        if original_type:
            inferred = original_type
            if original_type == "boolean":
                reason = "values are exclusively true/false style tokens"
            elif original_type in {"date", "datetime"}:
                reason = "values parse as dates"
            elif original_type == "currency":
                reason = "values carry a currency symbol"
            elif original_type == "mixed_numeric":
                reason = "some but not all values parse as numbers"
        missing = int(series.isna().sum())
        missing_pct = round(missing / row_count * 100, 2) if row_count else 0.0
        non_null = series.dropna()

        samples: list[Any] = []
        for value in non_null.head(5).tolist():
            cleaned = _clean(value)
            if isinstance(cleaned, str) and redact_samples and len(cleaned) > 120:
                cleaned = cleaned[:117] + "..."
            samples.append(cleaned)

        stats: dict[str, Any] = {}
        currency: str | None = None
        if inferred in {"numeric", "currency", "mixed_numeric"} and not pd.api.types.is_bool_dtype(series):
            numeric = _numeric_series(series).dropna()
            if len(numeric):
                stats = {
                    "count": int(numeric.count()),
                    "mean": _clean(numeric.mean()),
                    "std": _clean(numeric.std()) if len(numeric) > 1 else 0.0,
                    "min": _clean(numeric.min()),
                    "max": _clean(numeric.max()),
                    "q25": _clean(numeric.quantile(0.25)),
                    "median": _clean(numeric.median()),
                    "q75": _clean(numeric.quantile(0.75)),
                    "sum": _clean(numeric.sum()),
                }
            if inferred == "currency":
                source_values = (
                    original[name].dropna().astype(str).head(50).tolist()
                    if original is not None and str(name) in original.columns
                    else non_null.astype(str).head(50).tolist()
                )
                currency = detect_currency(source_values)
        elif inferred in {"date", "datetime"}:
            parsed = to_datetime_series(series).dropna()
            if original is not None and str(name) in original.columns:
                parsed_original = to_datetime_series(original[name]).dropna()
                if not parsed_original.empty:
                    parsed = parsed_original
            if len(parsed):
                stats = {
                    "min": parsed.min().isoformat(),
                    "max": parsed.max().isoformat(),
                    "distinct_periods": int(parsed.dt.to_period("M").nunique())
                    if inferred == "date"
                    else int(parsed.nunique()),
                }
        else:
            try:
                stats = {"distinct": int(non_null.nunique())}
                top = non_null.value_counts().head(3)
                stats["top_values"] = [{"value": _clean(k), "count": int(v)} for k, v in top.items()]
            except TypeError:  # pragma: no cover - unhashable values
                stats = {}

        unique_count = int(non_null.nunique()) if row_count <= 200_000 else None
        role = role_for_column(str(name), inferred)

        columns.append(
            {
                "name": str(name),
                "position": position,
                "dtype": str(series.dtype),
                "inferred_type": inferred,
                "inference_reason": reason,
                "nullable": bool(missing > 0),
                "missing_count": missing,
                "missing_pct": missing_pct,
                "unique_count": unique_count,
                "sample_values": samples,
                "stats": stats,
                "currency": currency,
                "role_hint": role,
            }
        )

        if missing_pct > 30:
            warnings.append(f"Column '{name}' is {missing_pct:.1f}% empty.")
        if looks_like_formula(str(name)):
            warnings.append(
                f"Column name '{name}' looks like a spreadsheet formula; it is quoted safely and sanitised on export."
            )
        if _INJECTION_HEADER_RE.search(str(name)):
            warnings.append(
                f"Column name '{name}' contains instruction-like text. It is treated as data, never as a command."
            )

    if row_count == 0:
        warnings.append("The dataset contains no rows.")
    if not frame.columns.size:
        warnings.append("The dataset contains no columns.")

    return {
        "row_count": row_count,
        "column_count": int(len(frame.columns)),
        "columns": columns,
        "warnings": warnings,
    }


def quality_report(frame: pd.DataFrame) -> dict[str, Any]:
    """Data-quality assessment with a transparent 0-100 score."""
    row_count = int(len(frame))
    column_count = int(len(frame.columns))
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    missing_by_column: dict[str, dict[str, Any]] = {}
    for name in frame.columns:
        missing = int(frame[name].isna().sum())
        pct = round(missing / row_count * 100, 2) if row_count else 0.0
        missing_by_column[str(name)] = {"missing": missing, "total": row_count, "pct": pct}
        if missing:
            issues.append(
                {
                    "type": "missing_values",
                    "severity": "high" if pct >= 30 else "medium" if pct >= 5 else "low",
                    "column": str(name),
                    "detail": f"{missing} of {row_count} rows are empty ({pct}%)",
                }
            )

    duplicate_mask = frame.duplicated() if row_count else pd.Series(dtype=bool)
    duplicate_count = int(duplicate_mask.sum()) if row_count else 0
    duplicate_pct = round(duplicate_count / row_count * 100, 2) if row_count else 0.0
    if duplicate_count:
        issues.append(
            {
                "type": "duplicate_rows",
                "severity": "high" if duplicate_pct >= 5 else "medium",
                "column": None,
                "detail": f"{duplicate_count} fully duplicated rows ({duplicate_pct}% of the dataset)",
            }
        )

    outliers: dict[str, Any] = {}
    for name in frame.columns:
        series = frame[name]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            continue
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric) < 10:
            continue
        q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((numeric < low) | (numeric > high)).sum())
        if count:
            pct = round(count / len(numeric) * 100, 2)
            outliers[str(name)] = {
                "count": count,
                "pct": pct,
                "lower": float(low),
                "upper": float(high),
            }
            issues.append(
                {
                    "type": "outliers",
                    "severity": "medium" if pct >= 10 else "low",
                    "column": str(name),
                    "detail": f"{count} values ({pct}%) fall outside [{float(low):.2f}, {float(high):.2f}]",
                }
            )

    type_issues: list[dict[str, Any]] = []
    constant_columns: list[str] = []
    for name in frame.columns:
        series = frame[name]
        non_null = series.dropna()
        if row_count and non_null.empty:
            type_issues.append({"column": str(name), "detail": "column is entirely empty"})
            continue
        if non_null.nunique() == 1 and row_count:
            constant_columns.append(str(name))
        if (
            not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series)
        ) and not pd.api.types.is_datetime64_any_dtype(series):
            text = non_null.astype(str).head(100)
            if len(text):
                numeric_like = sum(1 for v in text if to_decimal(v) is not None)
                if 0 < numeric_like < len(text):
                    type_issues.append(
                        {
                            "column": str(name),
                            "detail": "mixes numeric and free-text values",
                        }
                    )

    injected_columns = [str(name) for name in frame.columns if scan_text_for_injection(str(name))]
    if injected_columns:
        warnings.append(
            "Instruction-like text was found in column headers (" + ", ".join(injected_columns[:5]) + "). "
            "Headers are always treated as data, never as commands."
        )

    # ---- score ------------------------------------------------------------
    score = 100.0
    if row_count:
        overall_missing = sum(v["missing"] for v in missing_by_column.values()) / (
            row_count * max(column_count, 1)
        )
        score -= min(30.0, overall_missing * 100)
    if duplicate_pct:
        score -= min(20.0, duplicate_pct)
    if outliers:
        score -= min(15.0, len(outliers) * 3.0)
    if type_issues:
        score -= min(10.0, len(type_issues) * 2.0)
    if constant_columns:
        score -= min(5.0, len(constant_columns) * 1.0)
    score = round(max(0.0, min(100.0, score)), 1)

    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate rows detected ({duplicate_pct}%).")
    high_missing = [c for c, v in missing_by_column.items() if v["pct"] >= 5]
    if high_missing:
        warnings.append(f"Columns with at least 5% missing values: {', '.join(high_missing[:8])}.")
    if constant_columns:
        warnings.append(f"Constant columns (no analytical value): {', '.join(constant_columns[:8])}.")
    if not warnings:
        warnings.append("No significant data-quality issues were detected.")

    return {
        "score": score,
        "row_count": row_count,
        "column_count": column_count,
        "missing_values": missing_by_column,
        "duplicates": {"count": duplicate_count, "pct": duplicate_pct},
        "outliers": outliers,
        "type_issues": type_issues,
        "constant_columns": constant_columns,
        "issues": issues,
        "warnings": warnings,
    }


def currency_symbol_for(code: str) -> str:
    for symbol, iso in CURRENCY_SYMBOLS.items():
        if iso == code:
            return symbol
    return ""


def coerce_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Normalise column dtypes so the query engine can aggregate reliably.

    Currency-like text (``"$1,234.56"``) becomes a numeric column, date-like
    text becomes a real timestamp and boolean-like text becomes a boolean.
    The *original* inference is returned so the schema viewer can still say
    "this is a currency column" instead of a plain "numeric" one.
    """
    coerced = frame.copy()
    raw_types: dict[str, str] = {}

    for name in frame.columns:
        series = frame[name]
        inferred, _reason = infer_column_type(series)
        raw_types[str(name)] = inferred

        if inferred in {"currency", "mixed_numeric"}:
            converted = series.map(lambda v: to_decimal(v))
            numeric = pd.to_numeric(converted, errors="coerce")
            coerced[name] = numeric.astype("float64")
        elif inferred == "date" or inferred == "datetime":
            parsed = to_datetime_series(series)
            coerced[name] = parsed
        elif inferred == "boolean" and not pd.api.types.is_bool_dtype(series):
            lowered = series.astype(str).str.strip().str.lower()
            coerced[name] = lowered.map(
                lambda v: True if v in _TRUE_VALUES else (False if v in _FALSE_VALUES else pd.NA)
            ).astype("boolean")

    return coerced, raw_types
