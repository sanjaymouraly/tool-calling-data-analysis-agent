"""Health, capability discovery and the audit trail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..db.base import get_db
from ..db.models import AuditLog
from ..domain.kpis import describe_catalogue
from ..providers.registry import PROVIDER_INFO
from ..tools.base import registry

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
    }


@router.get("/info")
def info() -> dict[str, Any]:
    return {
        "app": settings.app_name,
        "slug": settings.app_slug,
        "version": settings.version,
        "environment": settings.environment,
        "tool_count": len(registry.names()),
        "tools": registry.names(),
        "providers": [
            {
                "name": name,
                "label": info.label,
                "requires_key": info.requires_key,
                "default_base_url": info.default_base_url,
                "default_model": info.default_model,
                "notes": info.notes,
            }
            for name, info in PROVIDER_INFO.items()
        ],
        "kpis": [kpi["name"] for kpi in describe_catalogue()],
        "limits": {
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_rows_ingested": settings.max_rows_ingested,
            "max_tool_rounds": settings.max_tool_rounds,
            "max_tool_result_rows": settings.max_tool_result_rows,
            "max_tool_result_bytes": settings.max_tool_result_bytes,
            "tool_timeout_seconds": settings.tool_timeout_seconds,
        },
        "security": {
            "arbitrary_code_execution": False,
            "model_supplied_sql": False,
            "tool_allowlist_size": len(registry.names()),
            "dataset_scoping": "per-request authorisation",
        },
    }


@router.get("/audit")
def audit_log(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "target_id": r.target_id,
            "details": r.details_json,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
