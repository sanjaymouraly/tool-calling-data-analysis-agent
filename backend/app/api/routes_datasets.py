"""Dataset management endpoints."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.errors import AppError
from ..core.logging import get_logger
from ..db.base import get_db
from ..db.models import Dataset
from ..domain.schemas import DatasetDetailOut, DatasetOut, PreviewOut, QualityOut, SchemaOut
from ..ingest import store
from ..ingest.readers import list_sheets
from ..tools import export as export_helpers

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
log = get_logger("api.datasets")

ALLOWED_UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xlsm", ".parquet"}


@router.get("", response_model=list[DatasetOut])
def list_datasets(
    db: Session = Depends(get_db),
    include_demo: bool = Query(True),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(200, ge=1, le=1000),
) -> list[Dataset]:
    return store.list_datasets(db, include_demo=include_demo, search=search, limit=limit)


@router.get("/{dataset_id}", response_model=DatasetDetailOut)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DatasetDetailOut:
    dataset = store.get_dataset(db, dataset_id)
    return DatasetDetailOut(
        **DatasetOut.model_validate(dataset).model_dump(),
        profile=dataset.schema_json or {},
        quality_report=dataset.quality_json or {},
    )


@router.post("/upload", status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None, max_length=255),
    description: str | None = Form(None, max_length=2000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type '{suffix or 'unknown'}'. Allowed: CSV, XLSX, XLSM, Parquet.",
        )

    raw = await file.read()
    if len(raw) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"the file exceeds the {settings.max_upload_size_mb}MB upload limit",
        )
    try:
        stored = store.create_dataset(
            db,
            raw=raw,
            filename=filename,
            sheet_name=sheet_name,
            description=description,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    dataset = stored.dataset
    return {
        "id": dataset.id,
        "name": dataset.name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "file_hash": dataset.source_hash,
        "sheet_name": dataset.sheet_name,
        "version": dataset.version,
        "is_demo": dataset.is_demo,
        "available_sheets": _available_sheets(dataset),
    }


def _available_sheets(dataset: Dataset) -> list[str]:
    if dataset.file_type not in {"xlsx", "xlsm"}:
        return []
    try:
        return list_sheets(Path(dataset.source_path))
    except Exception:  # pragma: no cover - the file may have been removed
        return []


@router.get("/{dataset_id}/sheets")
def dataset_sheets(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = store.get_dataset(db, dataset_id)
    return {"dataset_id": dataset.id, "sheets": _available_sheets(dataset)}


@router.get("/{dataset_id}/schema", response_model=SchemaOut)
def dataset_schema(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = store.get_dataset(db, dataset_id)
    profile = dataset.schema_json or {}
    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "columns": profile.get("columns", []),
        "warnings": profile.get("warnings", []),
        "currency": dataset.currency or "USD",
    }


@router.get("/{dataset_id}/preview", response_model=PreviewOut)
def dataset_preview(
    dataset_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    columns: str | None = Query(None, max_length=2000),
) -> dict[str, Any]:
    from ..engine.duck import execute_dataframe, quote_identifier, source_clause

    dataset = store.get_dataset(db, dataset_id)
    allowed = [str(c.get("name")) for c in (dataset.schema_json or {}).get("columns", [])]
    select_list = "*"
    if columns:
        requested = [c.strip() for c in columns.split(",") if c.strip()]
        unknown = [c for c in requested if c not in allowed]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown columns: {', '.join(unknown[:10])}")
        select_list = ", ".join(quote_identifier(c, allowed) for c in requested)

    source, params = source_clause(store.artifact_for(dataset))
    frame = execute_dataframe(
        f"SELECT {select_list} FROM {source} LIMIT {int(limit)} OFFSET {int(offset)}", params
    )
    records = [
        {
            str(k): (
                None
                if v is None or (isinstance(v, float) and v != v)
                else (v.isoformat() if hasattr(v, "isoformat") else v)
            )
            for k, v in row.items()
        }
        for row in frame.to_dict(orient="records")
    ]
    return {
        "dataset_id": dataset.id,
        "rows": records,
        "columns": [str(c) for c in frame.columns],
        "total_rows": dataset.row_count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{dataset_id}/quality", response_model=QualityOut)
def dataset_quality(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    dataset = store.get_dataset(db, dataset_id)
    report = dict(dataset.quality_json or {})
    report["dataset_id"] = dataset.id
    return report


@router.get("/{dataset_id}/columns")
def dataset_columns(
    dataset_id: str,
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=200),
) -> dict[str, Any]:
    dataset = store.get_dataset(db, dataset_id)
    columns = (dataset.schema_json or {}).get("columns", [])
    if q:
        needle = q.lower()
        columns = [c for c in columns if needle in str(c.get("name", "")).lower()]
    return {"dataset_id": dataset.id, "count": len(columns), "columns": columns}


@router.get("/{dataset_id}/export")
def export_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    format: str = Query("csv", pattern="^(csv|xlsx|json)$"),
    limit: int = Query(10000, ge=1, le=100000),
) -> StreamingResponse:
    from ..engine.duck import execute_dataframe, source_clause

    dataset = store.get_dataset(db, dataset_id)
    source, params = source_clause(store.artifact_for(dataset))
    frame = execute_dataframe(f"SELECT * FROM {source} LIMIT {int(limit)}", params)

    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in dataset.name)
    if format == "csv":
        payload = export_helpers.to_csv_bytes(frame)
        media = "text/csv"
    elif format == "xlsx":
        payload = export_helpers.to_xlsx_bytes(frame)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        payload = export_helpers.to_json_bytes(frame)
        media = "application/json"

    return StreamingResponse(
        io.BytesIO(payload),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.{format}"'},
    )


@router.post("/{dataset_id}/approve")
def approve_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    approved: bool = Query(True),
) -> dict[str, Any]:
    dataset = store.set_approved(db, dataset_id, approved)
    return {"id": dataset.id, "is_approved": dataset.is_approved}


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    store.delete_dataset(db, dataset_id)
    return {"ok": True, "deleted": dataset_id}


@router.post("/demo/seed", status_code=201)
def seed_demo_datasets(db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..demo import seed

    created = seed.seed_demo_datasets(db, force=True)
    return {"ok": True, "created": created}
