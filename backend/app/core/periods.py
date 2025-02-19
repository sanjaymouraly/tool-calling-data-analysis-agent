"""Date, time-zone and calendar-period helpers.

All boundaries are computed on timezone-naive timestamps.  The application
stores dates exactly as they appear in the source file (no implicit timezone
conversion) so that a monthly bucket always means "the calendar month as
written in the data".
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

#: Buckets understood by the time-bucketing engine.
BUCKETS = ("day", "week", "month", "quarter", "year")

_QUARTER_RE = re.compile(r"^(\d{4})[- ]?Q([1-4])$", re.IGNORECASE)
_MONTH_RE = re.compile(r"^(\d{4})[- ]?(\d{1,2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")


@dataclass(frozen=True)
class Period:
    """An inclusive-start, inclusive-end calendar period."""

    label: str
    start: date
    end: date

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "start": self.start.isoformat(), "end": self.end.isoformat()}


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    if quarter < 1 or quarter > 4:
        raise ValueError(f"quarter must be 1..4, got {quarter}")
    start_month = 3 * (quarter - 1) + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def month_bounds(year: int, month: int) -> tuple[date, date]:
    if month < 1 or month > 12:
        raise ValueError(f"month must be 1..12, got {month}")
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def resolve_period(spec: str) -> Period:
    """Resolve a textual period such as ``2024-Q1``, ``2024-03`` or ``2024``."""
    text = (spec or "").strip()
    if not text:
        raise ValueError("empty period specification")

    match = _QUARTER_RE.match(text)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
        start, end = quarter_bounds(year, quarter)
        return Period(f"{year}-Q{quarter}", start, end)

    match = _MONTH_RE.match(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        start, end = month_bounds(year, month)
        return Period(f"{year}-{month:02d}", start, end)

    match = _YEAR_RE.match(text)
    if match:
        year = int(match.group(1))
        start, end = year_bounds(year)
        return Period(str(year), start, end)

    # ISO date
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"unsupported period '{spec}'. Use YYYY, YYYY-MM, YYYY-Q[1-4] or an ISO date."
        ) from exc
    return Period(parsed.isoformat(), parsed, parsed)


def previous_period(spec: str) -> Period:
    """The period immediately preceding ``spec`` with the same granularity."""
    period = resolve_period(spec)
    if _QUARTER_RE.match(spec.strip()):
        year = period.start.year
        quarter = (period.start.month - 1) // 3 + 1
        if quarter == 1:
            year, quarter = year - 1, 4
        else:
            quarter -= 1
        start, end = quarter_bounds(year, quarter)
        return Period(f"{year}-Q{quarter}", start, end)
    if _MONTH_RE.match(spec.strip()):
        year, month = period.start.year, period.start.month
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
        start, end = month_bounds(year, month)
        return Period(f"{year}-{month:02d}", start, end)
    start, end = year_bounds(period.start.year - 1)
    return Period(str(period.start.year - 1), start, end)


def period_for_date(value: pd.Timestamp, bucket: str) -> str:
    """Label of the bucket a timestamp belongs to."""
    ts = pd.Timestamp(value)
    if bucket == "day":
        return ts.strftime("%Y-%m-%d")
    if bucket == "week":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if bucket == "month":
        return ts.strftime("%Y-%m")
    if bucket == "quarter":
        return f"{ts.year}-Q{(ts.month - 1) // 3 + 1}"
    if bucket == "year":
        return str(ts.year)
    raise ValueError(f"unsupported bucket '{bucket}'")


def bucket_bounds(label: str, bucket: str) -> tuple[date, date]:
    """Start/end dates for a bucket label produced by :func:`period_for_date`."""
    if bucket == "day":
        parsed = date.fromisoformat(label)
        return parsed, parsed
    if bucket == "week":
        year, week = label.split("-W")
        start = date.fromisocalendar(int(year), int(week), 1)
        return start, start + timedelta(days=6)
    if bucket == "month":
        year_number, month_number = (int(part) for part in label.split("-"))
        return month_bounds(year_number, month_number)
    if bucket == "quarter":
        year_part, quarter_part = label.split("-Q")
        return quarter_bounds(int(year_part), int(quarter_part))
    if bucket == "year":
        return year_bounds(int(label))
    raise ValueError(f"unsupported bucket '{bucket}'")


def to_datetime_series(series: pd.Series) -> pd.Series:
    """Parse a column into timezone-naive timestamps, coercing bad values."""
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = series
    else:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_localize(None)
    return parsed


def parse_date(value: Any) -> datetime | None:
    """Parse a single value into a naive datetime, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.to_datetime(text, errors="raise", format="mixed")
    except Exception:
        return None
    if isinstance(parsed, pd.Timestamp):
        if parsed.tzinfo is not None:
            parsed = parsed.tz_localize(None)
        return parsed.to_pydatetime()
    return None


def date_range_of(series: pd.Series) -> tuple[str | None, str | None]:
    """Min/max ISO dates of a parsed datetime series."""
    parsed = to_datetime_series(series).dropna()
    if parsed.empty:
        return None, None
    return parsed.min().date().isoformat(), parsed.max().date().isoformat()


def business_days_between(start: date, end: date) -> int:
    """Inclusive count of business days (Mon-Fri) between two dates."""
    if end < start:
        return 0
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5)


def known_periods(series: pd.Series, bucket: str) -> list[str]:
    """Ordered list of the bucket labels present in a datetime column."""
    parsed = to_datetime_series(series).dropna()
    labels = {period_for_date(ts, bucket) for ts in parsed}
    return sorted(labels)


def summarise_periods(periods: Iterable[str]) -> dict[str, Any]:
    """Summarise a list of period labels for display in the evidence panel."""
    items = list(periods)
    if not items:
        return {"count": 0, "first": None, "last": None}
    return {"count": len(items), "first": items[0], "last": items[-1]}
