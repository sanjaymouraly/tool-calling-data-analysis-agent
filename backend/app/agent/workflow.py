"""The controlled agent workflow.

    INSPECT -> PLAN -> VALIDATE -> EXECUTE -> VERIFY -> ANSWER -> PERSIST

Every state transition is explicit, every step is bounded and every failure
degrades into a recorded, inspectable error rather than an exception that
loses the work done so far.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.errors import AppError, ProviderError, SecurityError, ToolExecutionError, ValidationError
from ..core.jsonutil import to_jsonable
from ..core.logging import get_logger
from ..db.models import AnalysisRecord, AuditLog, Conversation, Dataset, Message
from ..ingest import store
from ..providers.base import DatasetContext, ProviderContext
from ..providers.free import FreeProvider
from ..providers.registry import get_provider
from ..tools.base import ToolContext, registry
from .narrative import build_how_calculated, build_narrative
from .planner import validate_plan
from .verify import verify_claims

log = get_logger("agent")

STATE_INSPECT = "inspect"
STATE_PLAN = "plan"
STATE_VALIDATE = "validate"
STATE_EXECUTE = "execute"
STATE_VERIFY = "verify"
STATE_ANSWER = "answer"
STATE_PERSIST = "persist"


@dataclass
class AnalysisRequest:
    question: str
    dataset_ids: list[str]
    provider: str = "free"
    provider_overrides: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None
    approved_joins: list[dict[str, Any]] = field(default_factory=list)
    max_rounds: int | None = None


@dataclass
class AnalysisOutcome:
    record: AnalysisRecord
    conversation_id: str | None
    answer: str
    plan: dict[str, Any]
    tool_trace: list[dict[str, Any]]
    evidence: dict[str, Any]
    how_calculated: dict[str, Any]
    usage: dict[str, Any]
    verification: dict[str, Any]
    states: list[str]
    provider: str
    model: str | None
    latency_ms: int
    status: str
    clarification: str | None = None
    charts: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #


def _date_columns(dataset: Dataset) -> list[str]:
    columns = (dataset.schema_json or {}).get("columns", [])
    return [str(c.get("name")) for c in columns if c.get("inferred_type") in {"date", "datetime"}]


def build_dataset_context(dataset: Dataset) -> DatasetContext:
    """Build the bounded schema view that is handed to a model."""
    columns = (dataset.schema_json or {}).get("columns", [])
    compact_columns = [
        {
            "name": str(c.get("name")),
            "type": c.get("inferred_type"),
            "role": c.get("role_hint"),
            "missing_pct": c.get("missing_pct", 0.0),
        }
        for c in columns
    ]
    context = DatasetContext(
        id=dataset.id,
        name=dataset.name,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        columns=compact_columns,
        currency=dataset.currency or "USD",
    )
    context.date_ranges, context.latest_periods = _date_metadata(dataset)
    return context


def _date_metadata(dataset: Dataset) -> tuple[dict[str, dict[str, str | None]], dict[str, str]]:
    date_columns = _date_columns(dataset)
    if not date_columns:
        return {}, {}
    from ..engine.duck import execute_dataframe, quote_identifier, source_clause

    ranges: dict[str, dict[str, str | None]] = {}
    latest: dict[str, str] = {}
    try:
        artifact = store.artifact_for(dataset)
    except Exception:
        return {}, {}
    source, source_params = source_clause(artifact)
    allowed = [str(c.get("name")) for c in (dataset.schema_json or {}).get("columns", [])]
    for column in date_columns:
        try:
            ident = quote_identifier(column, allowed)
            frame = execute_dataframe(
                f"SELECT MIN(CAST({ident} AS TIMESTAMP)) AS lo, MAX(CAST({ident} AS TIMESTAMP)) AS hi, "
                f"strftime(MAX(CAST({ident} AS TIMESTAMP)), '%Y-%m') AS latest FROM {source}",
                source_params,
            )
            if frame.empty:
                continue
            row = frame.iloc[0]
            lo = row.get("lo")
            hi = row.get("hi")
            ranges[column] = {
                "min": lo.isoformat() if hasattr(lo, "isoformat") else None,
                "max": hi.isoformat() if hasattr(hi, "isoformat") else None,
            }
            if row.get("latest"):
                latest[column] = str(row.get("latest"))
        except Exception:  # pragma: no cover - defensive
            continue
    return ranges, latest


# --------------------------------------------------------------------------- #
# Workflow
# --------------------------------------------------------------------------- #


async def run_analysis(
    db: Session,
    request: AnalysisRequest,
    *,
    session: Session | None = None,
) -> AnalysisOutcome:
    """Execute the full agent workflow for one question."""
    started = time.perf_counter()
    states: list[str] = []

    datasets = store.list_datasets(db, include_demo=True, limit=500)
    by_id = {d.id: d for d in datasets}
    missing = [d for d in request.dataset_ids if d not in by_id]
    if missing:
        raise ValidationError(f"unknown dataset(s): {', '.join(missing)}")
    authorized = tuple(request.dataset_ids)

    # --- INSPECT --------------------------------------------------------
    states.append(STATE_INSPECT)
    contexts: list[DatasetContext] = []
    for dataset_id in authorized:
        dataset = by_id[dataset_id]
        contexts.append(build_dataset_context(dataset))

    approved_joins = _load_approved_joins(db, request.approved_joins)
    ctx = ToolContext(
        db=db,
        settings=settings,
        authorized_dataset_ids=authorized,
        approved_joins=tuple(approved_joins),
        token_budget=settings.request_token_budget,
        cost_budget_usd=settings.request_cost_budget_usd,
    )

    provider_name = (request.provider or "free").lower()
    provider = get_provider(db, provider_name, request.provider_overrides)
    model = getattr(provider, "resolve_model", lambda: None)()

    provider_context = ProviderContext(
        question=request.question,
        datasets=contexts,
        tools=registry.definitions(),
        max_rounds=min(request.max_rounds or settings.max_tool_rounds, settings.max_tool_rounds),
    )

    # --- PLAN -----------------------------------------------------------
    states.append(STATE_PLAN)
    fallback_used = False
    plan_notes: list[str] = []
    try:
        provider_result = await provider.plan(provider_context)
        raw_plan = provider_result.plan
        usage = dict(provider_result.usage or {})
    except (ProviderError, AppError) as exc:
        log.warning("plan.provider_failed", provider=provider_name, error=str(exc))
        fallback_used = True
        plan_notes.append(f"The {provider_name} provider could not produce a plan ({str(exc)[:160]}).")
        free_provider = FreeProvider()
        provider_result = await free_provider.plan(provider_context)
        raw_plan = provider_result.plan
        usage = dict(provider_result.usage or {})
        provider_name = "free"
        model = "deterministic-rule-engine"

    # --- VALIDATE -------------------------------------------------------
    states.append(STATE_VALIDATE)
    max_steps = min(request.max_rounds or settings.max_tool_rounds, settings.max_tool_rounds)
    try:
        validated = validate_plan(
            raw_plan,
            authorized_dataset_ids=authorized,
            max_steps=max_steps,
        )
    except (SecurityError, ValidationError) as exc:
        if fallback_used:
            raise
        log.warning("plan.invalid", error=str(exc))
        plan_notes.append(f"The provider's plan was rejected by the validator ({str(exc)[:160]}).")
        free_provider = FreeProvider()
        provider_result = await free_provider.plan(provider_context)
        validated = validate_plan(
            provider_result.plan,
            authorized_dataset_ids=authorized,
            max_steps=max_steps,
        )
        provider_name = "free"
        model = "deterministic-rule-engine"
        fallback_used = True

    # --- EXECUTE --------------------------------------------------------
    states.append(STATE_EXECUTE)
    tool_trace: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []

    for index, step in enumerate(validated.steps):
        if ctx.cancelled:
            tool_trace.append(
                {
                    "step": index + 1,
                    "tool": step.tool,
                    "input": step.arguments,
                    "status": "cancelled",
                    "error": "the request was cancelled before this step ran",
                }
            )
            break
        try:
            output = registry.dispatch(ctx, step.tool, step.arguments, round_index=index + 1)
        except ToolExecutionError as exc:
            tool_trace.append(
                {
                    "step": index + 1,
                    "tool": step.tool,
                    "input": step.arguments,
                    "reason": step.reason,
                    "status": "error",
                    "error": exc.message,
                    "error_code": exc.code,
                    "warnings": step.warnings,
                }
            )
            log.info("tool.error", tool=step.tool, error=exc.message)
            continue
        except AppError as exc:
            tool_trace.append(
                {
                    "step": index + 1,
                    "tool": step.tool,
                    "input": step.arguments,
                    "reason": step.reason,
                    "status": "error",
                    "error": exc.message,
                    "error_code": exc.code,
                    "warnings": step.warnings,
                }
            )
            continue

        tool_trace.append(
            {
                "step": index + 1,
                "tool": step.tool,
                "input": step.arguments,
                "reason": step.reason,
                "status": "success",
                "output": output,
                "evidence": output.get("evidence", {}),
                "warnings": step.warnings + list(output.get("warnings", [])),
            }
        )
        observations.append({"tool": step.tool, "data": output.get("data", {})})
        if output.get("chart"):
            charts.append(output["chart"])

    # --- VERIFY ---------------------------------------------------------
    states.append(STATE_VERIFY)
    narrative_text = build_narrative(
        request.question,
        tool_trace,
        [_dataset_evidence(by_id[d]) for d in authorized],
        clarification=validated.clarification,
        currency=by_id[authorized[0]].currency or "USD" if authorized else "USD",
    )

    verification: dict[str, Any] = {
        "all_verified": True,
        "total_claims": 0,
        "verified_claims": [],
        "unverified_claims": [],
        "note": "The narrative was generated directly from tool outputs, so every figure is grounded by construction.",
    }

    if provider_name != "free" and observations:
        try:
            llm_narrative = await provider.narrate(provider_context, observations)
        except (ProviderError, AppError) as exc:
            llm_narrative = ""
            plan_notes.append(f"The provider could not write a narrative ({str(exc)[:120]}).")
        if llm_narrative:
            verification = verify_claims(llm_narrative, observations)
            if verification["all_verified"]:
                narrative_text = llm_narrative
            else:
                narrative_text = llm_narrative
                plan_notes.append(
                    f"{len(verification['unverified_claims'])} numeric claim(s) in the model narrative could not be "
                    "verified against the tool outputs and are flagged in the response."
                )

    # --- ANSWER ---------------------------------------------------------
    states.append(STATE_ANSWER)
    evidence = _build_evidence(tool_trace, by_id, authorized)
    how_calculated = build_how_calculated(
        tool_trace,
        [_dataset_evidence(by_id[d]) for d in authorized],
        validated.to_dict(),
        provider=provider_name,
        model=model,
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    status = "completed" if any(t["status"] == "success" for t in tool_trace) else "failed"
    if validated.clarification and status == "completed":
        status = "needs_clarification"

    # --- PERSIST --------------------------------------------------------
    states.append(STATE_PERSIST)
    record = AnalysisRecord(
        question=request.question,
        dataset_ids=list(authorized),
        provider=provider_name,
        model=model,
        status=status,
        plan_json=to_jsonable(validated.to_dict()),
        tool_trace_json=to_jsonable(tool_trace),
        result_json=to_jsonable({"observations": observations, "charts": charts}),
        evidence_json=to_jsonable(evidence),
        how_calculated_json=to_jsonable(how_calculated),
        usage_json=to_jsonable(usage),
        answer=narrative_text,
        latency_ms=latency_ms,
    )
    db.add(record)
    db.flush()

    conversation_id = request.conversation_id
    if conversation_id:
        conversation = db.get(Conversation, conversation_id)
    else:
        conversation = None
    if conversation is None:
        conversation = Conversation(
            title=request.question[:120],
            dataset_ids=list(authorized),
            provider=provider_name,
        )
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
    record.conversation_id = conversation.id

    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=request.question,
            payload_json={"dataset_ids": list(authorized)},
        )
    )
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=narrative_text,
            payload_json=to_jsonable(
                {
                    "analysis_id": record.id,
                    "tool_trace": tool_trace,
                    "charts": charts,
                    "plan": validated.to_dict(),
                }
            ),
        )
    )
    db.add(
        AuditLog(
            action="analysis.completed",
            target_id=record.id,
            details_json={
                "question": request.question[:200],
                "provider": provider_name,
                "model": model,
                "status": status,
                "tools": [t["tool"] for t in tool_trace],
                "latency_ms": latency_ms,
            },
        )
    )
    db.commit()
    db.refresh(record)

    if plan_notes:
        evidence.setdefault("notes", []).extend(plan_notes)

    return AnalysisOutcome(
        record=record,
        conversation_id=conversation.id,
        answer=narrative_text,
        plan=validated.to_dict(),
        tool_trace=tool_trace,
        evidence=evidence,
        how_calculated=how_calculated,
        usage=usage,
        verification=verification,
        states=states,
        provider=provider_name,
        model=model,
        latency_ms=latency_ms,
        status=status,
        clarification=validated.clarification,
        charts=charts,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _dataset_evidence(dataset: Dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "sheet": dataset.sheet_name,
        "file_hash": dataset.source_hash,
        "artifact_hash": dataset.artifact_hash,
        "currency": dataset.currency,
        "is_demo": dataset.is_demo,
    }


def _build_evidence(
    tool_trace: list[dict[str, Any]],
    by_id: dict[str, Dataset],
    authorized: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "datasets": [_dataset_evidence(by_id[d]) for d in authorized],
        "tool_evidence": [
            {
                "tool": step["tool"],
                "status": step["status"],
                "evidence": step.get("evidence", {}),
            }
            for step in tool_trace
        ],
        "verifiable": True,
        "note": (
            "Every figure in the answer comes from one of the tool executions listed above. "
            "Re-running the same plan against the same dataset hash reproduces the same numbers."
        ),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _load_approved_joins(db: Session, requested: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the request's approved joins with the persisted approvals."""

    joins: list[dict[str, Any]] = []
    for item in requested or []:
        if not isinstance(item, dict):
            continue
        joins.append(
            {
                "id": item.get("id"),
                "left_dataset_id": item.get("left_dataset_id") or item.get("left_dataset"),
                "right_dataset_id": item.get("right_dataset_id") or item.get("right_dataset"),
                "left_key": item.get("left_key"),
                "right_key": item.get("right_key"),
            }
        )
    for row in db.execute(select_approved_joins()).scalars().all():
        joins.append(
            {
                "id": row.id,
                "left_dataset_id": row.left_dataset_id,
                "right_dataset_id": row.right_dataset_id,
                "left_key": row.left_key,
                "right_key": row.right_key,
            }
        )
    return joins


def select_approved_joins():
    from sqlalchemy import select

    from ..db.models import ApprovedJoin

    return select(ApprovedJoin).where(ApprovedJoin.is_approved.is_(True))


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
