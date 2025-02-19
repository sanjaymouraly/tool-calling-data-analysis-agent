"""Saved reports, exports and the audit trail."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import get_db
from ..db.models import AnalysisRecord, SavedReport
from ..domain.schemas import SavedReportIn, SavedReportOut
from ..tools import export as export_helpers

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[SavedReportOut])
def list_reports(db: Session = Depends(get_db)) -> list[SavedReport]:
    return list(db.execute(select(SavedReport).order_by(SavedReport.created_at.desc())).scalars().all())


@router.post("", response_model=SavedReportOut, status_code=201)
def create_report(req: SavedReportIn, db: Session = Depends(get_db)) -> SavedReport:
    report = SavedReport(
        title=req.title,
        analysis_id=req.analysis_id,
        dataset_id=req.dataset_id,
        chart_json=req.chart,
        notes=req.notes,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.delete("/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    report = db.get(SavedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    db.delete(report)
    db.commit()
    return {"ok": True, "deleted": report_id}


@router.get("/{report_id}/export")
def export_report(
    report_id: str,
    db: Session = Depends(get_db),
    format: str = Query("pdf", pattern="^(pdf|csv|json)$"),
) -> StreamingResponse:
    report = db.get(SavedReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")

    analysis = db.get(AnalysisRecord, report.analysis_id) if report.analysis_id else None
    chart = report.chart_json or {}
    rows = chart.get("data") or []

    if format == "json":
        import json

        payload = json.dumps(
            {
                "title": report.title,
                "chart": chart,
                "answer": analysis.answer if analysis else None,
                "evidence": analysis.evidence_json if analysis else None,
            },
            indent=2,
            default=str,
        ).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.json"'},
        )

    if format == "csv":
        frame = pd.DataFrame(rows) if rows else pd.DataFrame()
        payload = export_helpers.to_csv_bytes(frame)
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.csv"'},
        )

    sections = [
        {"heading": "Question", "body": analysis.question if analysis else report.title},
        {"heading": "Answer", "body": analysis.answer if analysis else "(no linked analysis)"},
        {"heading": "Provenance", "body": _provenance_text(analysis)},
    ]
    payload = export_helpers.to_pdf_bytes(
        title=report.title,
        sections=sections,
        table=pd.DataFrame(rows) if rows else None,
        table_title="Chart data",
    )
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'},
    )


def _provenance_text(analysis: AnalysisRecord | None) -> str:
    if analysis is None:
        return "No linked analysis record."
    evidence = analysis.evidence_json or {}
    lines = [f"Analysis id: {analysis.id}", f"Provider: {analysis.provider} ({analysis.model})"]
    for dataset in evidence.get("datasets", []):
        lines.append(
            f"Dataset: {dataset.get('name')} (id {str(dataset.get('id'))[:8]}, v{dataset.get('version')}, "
            f"{dataset.get('row_count')} rows, sha256 {str(dataset.get('file_hash'))[:12]})"
        )
    lines.append(f"Tools: {', '.join(s.get('tool', '?') for s in (analysis.tool_trace_json or []))}")
    lines.append(f"Generated at: {analysis.created_at.isoformat()}")
    return "\n".join(lines)
