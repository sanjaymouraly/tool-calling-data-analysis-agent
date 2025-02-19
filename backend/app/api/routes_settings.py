"""Settings: providers, metric definitions, approved joins, calendars, usage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.crypto import encrypt_secret, key_hint, mask_secret
from ..core.errors import AppError
from ..core.logging import get_logger
from ..db.base import get_db
from ..db.models import (
    ApprovedJoin,
    AuditLog,
    BusinessCalendar,
    MetricDefinition,
    ProviderConfig,
    UsageRecord,
)
from ..domain.kpis import describe_catalogue
from ..domain.schemas import (
    ApprovedJoinIn,
    ApprovedJoinInOut,
    MetricDefinitionIn,
    MetricDefinitionOut,
    ProviderConfigIn,
    ProviderStatusOut,
    ProviderTestIn,
)
from ..providers.registry import PROVIDER_INFO, PROVIDER_ORDER, get_provider, provider_status, resolve_options

router = APIRouter(prefix="/api/settings", tags=["settings"])
log = get_logger("api.settings")


@router.get("/config")
def get_config() -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "app_slug": settings.app_slug,
        "version": settings.version,
        "environment": settings.environment,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "max_tool_rounds": settings.max_tool_rounds,
        "max_tool_result_rows": settings.max_tool_result_rows,
        "tool_timeout_seconds": settings.tool_timeout_seconds,
        "request_cost_budget_usd": settings.request_cost_budget_usd,
        "request_token_budget": settings.request_token_budget,
        "default_provider": settings.default_provider,
        "kpi_catalogue": describe_catalogue(),
    }


@router.get("/providers", response_model=list[ProviderStatusOut])
def list_providers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in PROVIDER_ORDER:
        status = provider_status(db, name)
        config = db.execute(select(ProviderConfig).where(ProviderConfig.provider == name)).scalars().first()
        status["source"] = "database" if config is not None else "environment"
        if config is not None:
            status["model"] = config.model or status["model"]
            status["base_url"] = config.base_url or status["base_url"]
        out.append(status)
    return out


@router.get("/providers/{provider}/models")
async def list_models(provider: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    if provider not in PROVIDER_INFO:
        raise HTTPException(status_code=404, detail="unknown provider")
    adapter = get_provider(db, provider)
    try:
        models = await adapter.list_models()
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:  # pragma: no cover - network issues
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    return {"provider": provider, "models": models, "count": len(models)}


@router.post("/providers/test")
async def test_provider(req: ProviderTestIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(status_code=404, detail="unknown provider")
    info = PROVIDER_INFO[req.provider]
    overrides = {
        k: v
        for k, v in {
            "api_key": req.api_key,
            "base_url": req.base_url,
            "model": req.model,
        }.items()
        if v
    }
    adapter = get_provider(db, req.provider, overrides)
    if info.requires_key and not adapter.api_key:
        return {
            "ok": False,
            "provider": req.provider,
            "error": "an API key is required for this provider",
        }
    if req.provider == "custom" and not (
        overrides.get("base_url") or resolve_options(db, "custom").get("base_url")
    ):
        return {
            "ok": False,
            "provider": req.provider,
            "error": "a base URL is required for a custom provider",
        }
    try:
        result = await adapter.test_connection()
    except AppError as exc:
        return {"ok": False, "provider": req.provider, "error": exc.message}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "provider": req.provider, "error": str(exc)[:300]}
    return {**result, "provider": req.provider}


@router.post("/providers")
def save_provider(req: ProviderConfigIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if req.provider not in PROVIDER_INFO:
        raise HTTPException(status_code=404, detail="unknown provider")
    config = (
        db.execute(select(ProviderConfig).where(ProviderConfig.provider == req.provider)).scalars().first()
    )
    if config is None:
        config = ProviderConfig(provider=req.provider)
        db.add(config)

    if req.base_url:
        config.base_url = req.base_url
    if req.model:
        config.model = req.model
    if req.api_key:
        config.api_key_encrypted = encrypt_secret(req.api_key)
        config.api_key_masked = mask_secret(req.api_key)
        config.key_hint = key_hint(req.api_key)
    config.enabled = req.enabled
    config.price_input_per_mtok = req.price_input_per_mtok
    config.price_output_per_mtok = req.price_output_per_mtok

    db.add(
        AuditLog(
            action="provider.saved",
            target_id=req.provider,
            details_json={
                "provider": req.provider,
                "base_url": config.base_url,
                "model": config.model,
                "key_changed": bool(req.api_key),
            },
        )
    )
    db.commit()
    return {
        "ok": True,
        "provider": req.provider,
        "masked_key": config.api_key_masked,
        "model": config.model,
        "base_url": config.base_url,
    }


@router.delete("/providers/{provider}")
def delete_provider(provider: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    config = db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider)).scalars().first()
    if config is not None:
        db.delete(config)
        db.commit()
    return {"ok": True, "provider": provider}


@router.get("/usage")
def usage_summary(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    records = (
        db.execute(select(UsageRecord).order_by(UsageRecord.created_at.desc()).limit(limit)).scalars().all()
    )
    total_tokens = sum(r.total_tokens for r in records)
    total_cost = sum(r.estimated_cost_usd for r in records)
    by_provider: dict[str, dict[str, Any]] = {}
    for record in records:
        entry = by_provider.setdefault(
            record.provider, {"calls": 0, "tokens": 0, "cost_usd": 0.0, "latency_ms": 0}
        )
        entry["calls"] += 1
        entry["tokens"] += record.total_tokens
        entry["cost_usd"] = round(entry["cost_usd"] + record.estimated_cost_usd, 6)
        entry["latency_ms"] += record.latency_ms
    return {
        "calls": len(records),
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(total_cost, 6),
        "by_provider": by_provider,
        "records": [
            {
                "id": r.id,
                "provider": r.provider,
                "model": r.model,
                "purpose": r.purpose,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost_usd": r.estimated_cost_usd,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ],
        "note": "Costs are estimates computed from the configured per-model prices.",
    }


# --------------------------------------------------------------------------- #
# Metric definitions, joins and calendars
# --------------------------------------------------------------------------- #


@router.get("/metrics", response_model=list[MetricDefinitionOut])
def list_metrics(db: Session = Depends(get_db)) -> list[MetricDefinition]:
    return list(
        db.execute(select(MetricDefinition).order_by(MetricDefinition.created_at.desc())).scalars().all()
    )


@router.post("/metrics", response_model=MetricDefinitionOut, status_code=201)
def create_metric(req: MetricDefinitionIn, db: Session = Depends(get_db)) -> MetricDefinition:
    definition = MetricDefinition(
        dataset_id=req.dataset_id,
        name=req.name,
        label=req.label,
        kpi=req.kpi,
        params_json=req.params,
        unit=req.unit,
        currency=req.currency,
        is_approved=req.is_approved,
        description=req.description,
    )
    db.add(definition)
    db.add(
        AuditLog(
            action="metric.defined",
            target_id=definition.name,
            details_json={"kpi": req.kpi, "dataset_id": req.dataset_id},
        )
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/metrics/{metric_id}")
def delete_metric(metric_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    definition = db.get(MetricDefinition, metric_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="metric definition not found")
    db.delete(definition)
    db.commit()
    return {"ok": True, "deleted": metric_id}


@router.get("/joins", response_model=list[ApprovedJoinInOut])
def list_joins(db: Session = Depends(get_db)) -> list[ApprovedJoin]:
    return list(db.execute(select(ApprovedJoin).order_by(ApprovedJoin.created_at.desc())).scalars().all())


@router.post("/joins", response_model=ApprovedJoinInOut, status_code=201)
def create_join(req: ApprovedJoinIn, db: Session = Depends(get_db)) -> ApprovedJoin:
    join = ApprovedJoin(
        left_dataset_id=req.left_dataset_id,
        right_dataset_id=req.right_dataset_id,
        left_key=req.left_key,
        right_key=req.right_key,
        is_approved=True,
        notes=req.notes,
    )
    db.add(join)
    db.add(
        AuditLog(
            action="join.approved",
            target_id=join.id,
            details_json={
                "left": req.left_dataset_id,
                "right": req.right_dataset_id,
                "left_key": req.left_key,
                "right_key": req.right_key,
            },
        )
    )
    db.commit()
    db.refresh(join)
    return join


@router.delete("/joins/{join_id}")
def delete_join(join_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    join = db.get(ApprovedJoin, join_id)
    if join is None:
        raise HTTPException(status_code=404, detail="join not found")
    db.delete(join)
    db.commit()
    return {"ok": True, "deleted": join_id}


@router.get("/calendars")
def list_calendars(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(select(BusinessCalendar).order_by(BusinessCalendar.name)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "timezone": r.timezone,
            "workdays": r.workdays,
            "holidays": r.holidays,
            "fiscal_year_start_month": r.fiscal_year_start_month,
            "description": r.description,
        }
        for r in rows
    ]


@router.post("/calendars", status_code=201)
def create_calendar(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    calendar = BusinessCalendar(
        name=name,
        timezone=str(payload.get("timezone", "UTC")),
        workdays=list(payload.get("workdays", [0, 1, 2, 3, 4])),
        holidays=list(payload.get("holidays", [])),
        fiscal_year_start_month=int(payload.get("fiscal_year_start_month", 1)),
        description=payload.get("description"),
    )
    db.add(calendar)
    db.commit()
    db.refresh(calendar)
    return {"id": calendar.id, "name": calendar.name, "timezone": calendar.timezone}
