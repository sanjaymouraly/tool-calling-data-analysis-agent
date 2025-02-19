"""Plan validation.

A plan produced by a model is *never* executed directly.  It must pass
:func:`validate_plan`, which enforces:

* the tool exists in the allowlist;
* the arguments satisfy the tool's strict schema (unknown fields rejected);
* every referenced dataset is authorised for the request;
* the number of steps is within the configured budget;
* no value can smuggle code, a path or a URL into the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.errors import SecurityError, ValidationError
from ..core.security import scan_text_for_injection
from ..tools.base import ToolRegistry
from ..tools.base import registry as default_registry


@dataclass
class PlanStep:
    """One validated step of an analysis plan."""

    tool: str
    arguments: dict[str, Any]
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "input": self.arguments, "reason": self.reason}


@dataclass
class ValidatedPlan:
    steps: list[PlanStep]
    clarification: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.clarification:
            payload["clarification"] = self.clarification
        if self.notes:
            payload["notes"] = self.notes
        return payload


def validate_plan(
    plan: Any,
    *,
    authorized_dataset_ids: tuple[str, ...] | list[str],
    max_steps: int,
    tool_registry: ToolRegistry | None = None,
) -> ValidatedPlan:
    """Validate a raw plan produced by a provider."""
    tools = tool_registry or default_registry

    if not isinstance(plan, dict):
        raise ValidationError("the analysis plan must be a JSON object")
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list):
        raise ValidationError("the analysis plan must contain a 'steps' array")
    if not raw_steps:
        raise ValidationError("the analysis plan is empty")
    if len(raw_steps) > max_steps:
        raise ValidationError(
            f"the analysis plan has {len(raw_steps)} steps which exceeds the limit of {max_steps}"
        )

    authorized = set(authorized_dataset_ids)
    validated: list[PlanStep] = []

    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ValidationError(f"step {index + 1} is not an object")
        tool_name = raw_step.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValidationError(f"step {index + 1} does not name a tool")
        if tool_name not in tools.names():
            raise SecurityError(
                f"step {index + 1} requests the unknown tool '{tool_name}'",
                details={"allowed_tools": tools.names()},
            )
        arguments = raw_step.get("input", raw_step.get("arguments", {}))
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ValidationError(f"step {index + 1} arguments must be a JSON object")

        reason = raw_step.get("reason") or ""
        if not isinstance(reason, str):
            reason = str(reason)
        reason = reason[:500]

        # Strict schema validation (extra fields are rejected).
        parsed = tools.validate_input(tool_name, arguments)

        # Dataset authorisation.
        for field_name in ("dataset_id", "left_dataset_id", "right_dataset_id"):
            value = getattr(parsed, field_name, None)
            if isinstance(value, str) and value and value not in authorized:
                raise SecurityError(
                    f"step {index + 1} references the dataset '{value}' which is not authorised for this request",
                    details={"authorized_dataset_ids": sorted(authorized)},
                )

        warnings: list[str] = []
        hits = _scan_arguments(arguments)
        if hits:
            warnings.append(
                "argument values contained instruction-like text; they were treated as data only "
                f"({', '.join(sorted(set(hits)))})"
            )

        validated.append(
            PlanStep(
                tool=tool_name,
                arguments=parsed.model_dump(mode="json"),
                reason=reason,
                warnings=warnings,
            )
        )

    clarification = plan.get("clarification")
    if clarification is not None and not isinstance(clarification, str):
        clarification = str(clarification)
    if clarification:
        clarification = clarification[:600]

    notes = plan.get("notes")
    notes = [str(n)[:200] for n in notes] if isinstance(notes, list) else []

    return ValidatedPlan(steps=validated, clarification=clarification, notes=notes)


def _scan_arguments(arguments: dict[str, Any]) -> list[str]:
    """Look for instruction-like text inside argument values.

    Such values are not rejected - a cell may legitimately contain that text -
    but they are flagged so the trace records that the value was handled as
    data and never as a command.
    """
    hits: list[str] = []
    stack: list[Any] = [arguments]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
        elif isinstance(current, str):
            hits.extend(scan_text_for_injection(current))
    return hits
