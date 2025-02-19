"""Chart specification validation.

The chart tool produces a *declarative* specification.  Nothing in it is
executable: the frontend renders it with a charting library using the
declared type, axes and series.  Titles and labels are stripped of markup so
that a malicious cell value cannot inject HTML into the page.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.errors import ValidationError
from ..core.security import is_safe_identifier

CHART_TYPES = {
    "bar",
    "column",
    "line",
    "area",
    "pie",
    "donut",
    "scatter",
    "histogram",
    "heatmap",
    "table",
}

#: Hard limits keep chart payloads small and render fast.
MAX_POINTS = 2000
MAX_SERIES = 6
MAX_LABEL_LENGTH = 120

_TAG_RE = re.compile(r"<[^>]{0,200}>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_text(value: Any, max_length: int = MAX_LABEL_LENGTH) -> str:
    """Remove markup and control characters from a user-visible label."""
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace('"', "&quot;").replace("'", "&#39;")
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text


def validate_chart_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a chart specification."""
    chart_type = str(spec.get("chart_type") or spec.get("type") or "bar").lower()
    if chart_type not in CHART_TYPES:
        raise ValidationError(
            f"unsupported chart type '{chart_type}'",
            details={"allowed": sorted(CHART_TYPES)},
        )

    points = spec.get("data") or []
    if not isinstance(points, list):
        raise ValidationError("chart data must be a list of points")
    if len(points) > MAX_POINTS:
        raise ValidationError(f"chart data is limited to {MAX_POINTS} points")

    series_names: list[str] = []
    for point in points[:MAX_POINTS]:
        if not isinstance(point, dict):
            raise ValidationError("each chart data point must be an object")
        for key in point:
            if not isinstance(key, str) or len(key) > MAX_LABEL_LENGTH:
                raise ValidationError("chart data keys must be short strings")
            if key not in series_names:
                series_names.append(key)
    if len(series_names) > MAX_SERIES:
        raise ValidationError(f"a chart may contain at most {MAX_SERIES} series")

    x_key = spec.get("x_key") or "x"
    if not is_safe_identifier(x_key):
        raise ValidationError(f"invalid x axis key '{x_key}'")

    normalised_points: list[dict[str, Any]] = []
    for point in points:
        row: dict[str, Any] = {}
        for key, value in point.items():
            if key == x_key:
                row[key] = sanitize_text(value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = value
            else:
                row[key] = value
        normalised_points.append(row)

    return {
        "chart_type": chart_type,
        "title": sanitize_text(spec.get("title") or "Chart", max_length=200),
        "x_key": x_key,
        "y_keys": [k for k in series_names if k != x_key][:MAX_SERIES],
        "data": normalised_points,
        "x_label": sanitize_text(spec.get("x_label") or ""),
        "y_label": sanitize_text(spec.get("y_label") or ""),
        "currency": sanitize_text(spec.get("currency") or "", max_length=8),
        "note": sanitize_text(spec.get("note") or "", max_length=500),
        "evidence": spec.get("evidence", {}),
    }
