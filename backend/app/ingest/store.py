"""Dataset registry: persistence, lineage and versioning.

A dataset is the pair (original file, normalised Parquet artifact).  The
original file is preserved byte-for-byte together with its SHA-256 hash; the
artifact is a deterministic projection used by the query engine.  Re-uploading
identical content creates a new *version* of the same logical dataset rather
than a duplicate.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.errors import NotFoundError, ValidationError
from ..core.security import resolve_within, sanitize_filename
from ..db.models import AuditLog, Dataset, DatasetColumn, DatasetVersion
from .normalize import coerce_frame, profile_frame, quality_report
from .readers import ReadResult, read_source, validate_extension, write_parquet_artifact


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class StoredDataset:
    dataset: Dataset
    columns: list[DatasetColumn]
    version: DatasetVersion


def _write_source_file(raw: bytes, filename: str) -> tuple[Path, str]:
    safe_name = sanitize_filename(filename)
    ext = validate_extension(safe_name)
    dataset_id = str(uuid.uuid4())
    directory = settings.upload_dir / dataset_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = resolve_within(settings.upload_dir, directory / safe_name)
    destination.write_bytes(raw)
    return destination, ext


def create_dataset(
    db: Session,
    *,
    raw: bytes,
    filename: str,
    sheet_name: str | None = None,
    description: str | None = None,
    is_demo: bool = False,
) -> StoredDataset:
    """Ingest an uploaded file and register it as an analysable dataset."""
    if not raw:
        raise ValidationError("the uploaded file is empty")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise ValidationError(
            f"the file is {len(raw) / 1e6:.1f}MB which exceeds the {settings.max_upload_size_mb}MB limit"
        )

    source_path, _ext = _write_source_file(raw, filename)
    source_hash = hash_file(source_path)

    try:
        result: ReadResult = read_source(
            source_path, max_rows=settings.max_rows_ingested, sheet_name=sheet_name
        )
    except Exception:
        shutil.rmtree(source_path.parent, ignore_errors=True)
        raise

    if result.frame is None or not len(result.frame.columns):
        shutil.rmtree(source_path.parent, ignore_errors=True)
        raise ValidationError("the file does not contain any tabular columns")

    dataset_id = str(uuid.uuid4())
    artifact_path = settings.artifact_dir / f"{dataset_id}.parquet"

    # Coerce dtypes (currency text -> numeric, date text -> timestamp) so the
    # query engine can aggregate them reliably, then profile the result.
    coerced_frame, raw_types = coerce_frame(result.frame)
    artifact_hash = write_parquet_artifact(coerced_frame, artifact_path)

    profile = profile_frame(
        coerced_frame,
        redact_samples=settings.redact_cell_samples,
        raw_types=raw_types,
        original=result.frame,
    )
    for column in profile.get("columns", []):
        original_type = raw_types.get(column["name"])
        if original_type in {"currency", "mixed_numeric"}:
            column["coerced_to"] = "numeric"
        elif original_type in {"date", "datetime"}:
            column["coerced_to"] = "timestamp"
    quality = quality_report(coerced_frame)

    lineage_id = _resolve_lineage(db, source_hash, sheet_name)
    version_number = _next_version(db, lineage_id)

    dataset = Dataset(
        id=dataset_id,
        name=Path(sanitize_filename(filename)).stem.replace("_", " ").title()[:200],
        original_filename=Path(sanitize_filename(filename)).name,
        source_path=str(source_path),
        source_hash=source_hash,
        artifact_path=str(artifact_path),
        artifact_hash=artifact_hash,
        file_type=source_path.suffix.lower().lstrip("."),
        sheet_name=result.sheet_name,
        row_count=int(len(result.frame)),
        column_count=int(len(result.frame.columns)),
        size_bytes=len(raw),
        schema_json=profile,
        quality_json=quality,
        currency=_dominant_currency(profile),
        is_demo=is_demo,
        description=description,
        lineage_id=lineage_id,
        version=version_number,
    )
    db.add(dataset)
    db.flush()

    columns = _persist_columns(db, dataset, profile)
    version = DatasetVersion(
        dataset_id=dataset.id,
        version=version_number,
        source_hash=source_hash,
        artifact_hash=artifact_hash,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        change_note=description
        or ("Initial import" if version_number == 1 else "Re-import of the same content"),
    )
    db.add(version)
    db.add(
        AuditLog(
            action="dataset.created",
            target_id=dataset.id,
            details_json={
                "filename": dataset.original_filename,
                "source_hash": source_hash,
                "rows": dataset.row_count,
                "columns": dataset.column_count,
                "version": version_number,
                "is_demo": is_demo,
            },
        )
    )
    db.commit()
    db.refresh(dataset)
    return StoredDataset(dataset=dataset, columns=columns, version=version)


def _dominant_currency(profile: dict[str, Any]) -> str:
    currencies = [
        col.get("currency")
        for col in profile.get("columns", [])
        if col.get("inferred_type") == "currency" and col.get("currency")
    ]
    if not currencies:
        return "USD"
    return max(set(currencies), key=currencies.count)


def _resolve_lineage(db: Session, source_hash: str, sheet_name: str | None) -> str:
    """Re-use the lineage of an identical file so versions stay linked."""
    existing = (
        db.execute(
            select(Dataset).where(
                Dataset.source_hash == source_hash,
                Dataset.sheet_name == sheet_name,
                Dataset.deleted_at.is_(None),
            )
        )
        .scalars()
        .first()
    )
    return existing.lineage_id if existing else str(uuid.uuid4())


def _next_version(db: Session, lineage_id: str) -> int:
    existing = db.execute(select(Dataset).where(Dataset.lineage_id == lineage_id)).scalars().all()
    return max((d.version for d in existing), default=0) + 1


def _persist_columns(db: Session, dataset: Dataset, profile: dict[str, Any]) -> list[DatasetColumn]:
    columns: list[DatasetColumn] = []
    for spec in profile.get("columns", []):
        column = DatasetColumn(
            dataset_id=dataset.id,
            name=spec["name"],
            position=spec.get("position", 0),
            dtype=spec.get("dtype", "object"),
            inferred_type=spec.get("inferred_type", "string"),
            nullable=bool(spec.get("nullable", True)),
            unique_count=spec.get("unique_count"),
            missing_count=spec.get("missing_count", 0),
            missing_pct=spec.get("missing_pct", 0.0),
            sample_json=spec.get("sample_values", []),
            stats_json=spec.get("stats", {}),
            currency=spec.get("currency"),
            role_hint=spec.get("role_hint"),
        )
        db.add(column)
        columns.append(column)
    return columns


def get_dataset(db: Session, dataset_id: str, *, include_deleted: bool = False) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or (dataset.deleted_at and not include_deleted):
        raise NotFoundError(f"dataset '{dataset_id}' was not found")
    return dataset


def list_datasets(
    db: Session,
    *,
    include_demo: bool = True,
    search: str | None = None,
    limit: int = 200,
) -> list[Dataset]:
    stmt = select(Dataset).where(Dataset.deleted_at.is_(None)).order_by(Dataset.created_at.desc())
    if not include_demo:
        stmt = stmt.where(Dataset.is_demo.is_(False))
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(Dataset.name.ilike(pattern) | Dataset.original_filename.ilike(pattern))
    return list(db.execute(stmt.limit(limit)).scalars().all())


def dataset_columns(db: Session, dataset_id: str) -> list[DatasetColumn]:
    stmt = (
        select(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id).order_by(DatasetColumn.position)
    )
    return list(db.execute(stmt).scalars().all())


def column_names(db: Session, dataset_id: str) -> list[str]:
    return [c.name for c in dataset_columns(db, dataset_id)]


def delete_dataset(db: Session, dataset_id: str, *, remove_files: bool = True) -> None:
    dataset = get_dataset(db, dataset_id)
    name = dataset.name
    if remove_files:
        for path in (dataset.source_path, dataset.artifact_path):
            if path:
                try:
                    target = Path(path)
                    if target.exists():
                        target.unlink()
                except OSError:  # pragma: no cover - best effort cleanup
                    pass
        try:
            source_parent = Path(dataset.source_path).parent
            if source_parent.is_dir() and source_parent.name == dataset.id:
                shutil.rmtree(source_parent, ignore_errors=True)
        except OSError:  # pragma: no cover
            pass
    db.delete(dataset)
    db.add(AuditLog(action="dataset.deleted", target_id=dataset_id, details_json={"name": name}))
    db.commit()


def set_approved(db: Session, dataset_id: str, approved: bool) -> Dataset:
    dataset = get_dataset(db, dataset_id)
    dataset.is_approved = approved
    db.add(
        AuditLog(
            action="dataset.approval_changed",
            target_id=dataset_id,
            details_json={"approved": approved},
        )
    )
    db.commit()
    db.refresh(dataset)
    return dataset


def dataset_summary(dataset: Dataset) -> dict[str, Any]:
    """Compact representation used by the agent prompt and the tool output."""
    schema = dataset.schema_json or {}
    columns = schema.get("columns", [])
    return {
        "id": dataset.id,
        "name": dataset.name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "columns": [
            {
                "name": col.get("name"),
                "type": col.get("inferred_type"),
                "role": col.get("role_hint"),
                "missing_pct": col.get("missing_pct", 0.0),
            }
            for col in columns
        ],
    }


def artifact_for(dataset: Dataset) -> str:
    if not dataset.artifact_path or not Path(dataset.artifact_path).exists():
        raise NotFoundError(
            "the normalised artifact for this dataset is missing; re-import the file",
            details={"dataset_id": dataset.id},
        )
    return dataset.artifact_path


def iter_dataset_columns(profile: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return profile.get("columns", [])
