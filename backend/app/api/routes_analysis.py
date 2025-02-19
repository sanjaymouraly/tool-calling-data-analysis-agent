"""Analysis endpoints: conversational workspace, history and direct tool use."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.workflow import AnalysisRequest, run_analysis
from ..core.config import settings
from ..core.errors import AppError
from ..db.base import get_db
from ..db.models import AnalysisRecord, Conversation, Message
from ..domain.schemas import AnalysisRequestIn, AnalysisResponseOut, HistoryOut
from ..tools.base import ToolContext, registry

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/tools")
def list_tools() -> list[dict[str, Any]]:
    """The complete, finite tool catalogue exposed to the model."""
    return registry.definitions()


@router.get("/tools/catalogue")
def tool_catalogue() -> dict[str, Any]:
    return {"count": len(registry.names()), "tools": registry.catalogue()}


@router.post("/query", response_model=AnalysisResponseOut)
async def query(req: AnalysisRequestIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..providers.registry import PROVIDER_INFO

    if req.provider.lower() not in PROVIDER_INFO:
        raise HTTPException(
            status_code=422,
            detail=f"unknown provider '{req.provider}'. Available: {', '.join(sorted(PROVIDER_INFO))}",
        )
    try:
        outcome = await run_analysis(
            db,
            AnalysisRequest(
                question=req.question,
                dataset_ids=req.dataset_ids,
                provider=req.provider,
                conversation_id=req.conversation_id,
                approved_joins=[j.model_dump() for j in req.approved_joins],
                max_rounds=req.max_rounds,
            ),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "id": outcome.record.id,
        "conversation_id": outcome.conversation_id,
        "question": outcome.record.question,
        "answer": outcome.answer,
        "status": outcome.status,
        "plan": outcome.plan,
        "tool_trace": outcome.tool_trace,
        "evidence": outcome.evidence,
        "how_calculated": outcome.how_calculated,
        "charts": outcome.charts,
        "usage": outcome.usage,
        "verification": outcome.verification,
        "clarification": outcome.clarification,
        "provider": outcome.provider,
        "model": outcome.model,
        "latency_ms": outcome.latency_ms,
        "states": outcome.states,
    }


@router.get("/history", response_model=list[HistoryOut])
def history(
    db: Session = Depends(get_db),
    dataset_id: str | None = Query(None, max_length=64),
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AnalysisRecord]:
    stmt = select(AnalysisRecord).order_by(AnalysisRecord.created_at.desc())
    if dataset_id:
        stmt = stmt.where(AnalysisRecord.dataset_ids.contains([dataset_id]))
    if search:
        stmt = stmt.where(AnalysisRecord.question.ilike(f"%{search.strip()}%"))
    return list(db.execute(stmt.limit(limit).offset(offset)).scalars().all())


@router.get("/history/{analysis_id}")
def analysis_detail(analysis_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(AnalysisRecord, analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return {
        "id": record.id,
        "conversation_id": record.conversation_id,
        "question": record.question,
        "answer": record.answer,
        "status": record.status,
        "plan": record.plan_json,
        "tool_trace": record.tool_trace_json,
        "result": record.result_json,
        "evidence": record.evidence_json,
        "how_calculated": record.how_calculated_json,
        "usage": record.usage_json,
        "provider": record.provider,
        "model": record.model,
        "latency_ms": record.latency_ms,
        "created_at": record.created_at.isoformat(),
    }


@router.get("/conversations")
def conversations(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = (
        db.execute(select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)).scalars().all()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "dataset_ids": row.dataset_ids or [],
            "provider": row.provider,
            "message_count": len(row.messages or []),
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = (
        db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "dataset_ids": conversation.dataset_ids or [],
        "provider": conversation.provider,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "payload": m.payload_json,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    db.delete(conversation)
    db.commit()
    return {"ok": True, "deleted": conversation_id}


@router.post("/tools/execute")
def execute_tool_directly(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Run a single allowlisted tool (used by the visual query builder).

    The caller must name the datasets the tool is allowed to touch; the
    dispatcher enforces that scope.
    """
    tool_name = payload.get("tool")
    arguments = payload.get("arguments", {})
    dataset_ids = payload.get("dataset_ids", [])
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="tool and arguments are required")
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
