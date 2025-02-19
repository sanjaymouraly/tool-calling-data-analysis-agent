"""Visual query builder endpoints (API-free deterministic analysis)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.errors import AppError
from ..db.base import get_db
from ..domain.kpis import describe_catalogue
from ..tools.base import ToolContext, registry

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    return {"count": len(registry.names()), "tools": registry.catalogue()}


@router.get("/kpis")
def kpis() -> dict[str, Any]:
    return {"catalogue": describe_catalogue()}


@router.post("/run")
def run_tool(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run one allowlisted tool on behalf of the visual query builder."""
    tool_name = payload.get("tool")
    arguments = payload.get("arguments", {})
    dataset_ids = payload.get("dataset_ids", [])
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="tool and arguments are required")
    if not isinstance(dataset_ids, list):
        raise HTTPException(status_code=400, detail="dataset_ids must be a list")
    ctx = ToolContext(
        db=db,
        settings=settings,
        authorized_dataset_ids=tuple(dataset_ids),
        approved_joins=tuple(payload.get("approved_joins", [])),
    )
    try:
        return registry.dispatch(ctx, tool_name, arguments)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
