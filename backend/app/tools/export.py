"""Export writers.

All exports are sanitised against spreadsheet formula injection: a cell that
begins with ``=``, ``+``, ``-`` or ``@`` is prefixed with an apostrophe so
Excel / LibreOffice / Google Sheets treat it as text.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd

from ..core.errors import ValidationError
from ..core.security import sanitize_dataframe


def sanitized_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``frame`` with formula-injection neutralised."""
    return sanitize_dataframe(frame)


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    sanitized_frame(frame).to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")


def to_json_bytes(frame: pd.DataFrame) -> bytes:
    payload = json.loads(sanitized_frame(frame).to_json(orient="records", date_format="iso"))
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def to_xlsx_bytes(frame: pd.DataFrame, *, sheet_name: str = "data") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sanitized_frame(frame).to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return buffer.getvalue()


def to_pdf_bytes(
    *,
    title: str,
    sections: Sequence[dict[str, Any]],
    table: pd.DataFrame | None = None,
    table_title: str = "Data",
) -> bytes:
    """Render a simple, dependency-light PDF report."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover - reportlab is a hard dependency
        raise ValidationError("PDF export is unavailable: reportlab is not installed") from exc

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title=title[:120],
        author="Tool-Calling Data Analysis Agent",
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=13)
    heading = ParagraphStyle("heading", parent=styles["Heading2"], fontSize=12, spaceBefore=10)

    story: list[Any] = [Paragraph(title, styles["Title"]), Spacer(1, 6 * mm)]
    for section in sections:
        if section.get("heading"):
            story.append(Paragraph(str(section["heading"]), heading))
        content = str(section.get("body") or "")
        for line in content.splitlines() or [""]:
            story.append(Paragraph(line.replace("&", "&amp;"), body))
        story.append(Spacer(1, 3 * mm))

    if table is not None and not table.empty:
        story.append(Paragraph(table_title, heading))
        preview = table.head(40)
        columns = [str(c)[:24] for c in preview.columns]
        rows = [columns] + [
            [str(value)[:40] if value is not None else "" for value in row]
            for row in preview.itertuples(index=False)
        ]
        table_obj = Table(rows, repeatRows=1, hAlign="LEFT")
        table_obj.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ]
            )
        )
        story.append(table_obj)

    doc.build(story)
    return buffer.getvalue()


def rows_to_frame(rows: Iterable[dict[str, Any]], columns: Sequence[str] | None = None) -> pd.DataFrame:
    rows = list(rows)
    if not rows:
        return pd.DataFrame(columns=list(columns or []))
    return pd.DataFrame(rows, columns=list(columns) if columns else None)
