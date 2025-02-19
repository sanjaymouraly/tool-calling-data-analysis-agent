"""Tool registry and dispatcher.

This module *is* the security boundary of the application.  A tool call from
the language model is only ever a ``(name, arguments)`` pair:

* the name must exist in the registry (no dynamic registration, no imports);
* the arguments are validated by a strict Pydantic model (``extra=forbid``);
* every dataset referenced by the arguments must be in the authorised set for
  the current request;
* the handler receives no access to the network, the filesystem or the
  process environment - it can only use the helpers in this package.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import SecurityError, ToolExecutionError, ValidationError
from ..core.logging import get_logger

log = get_logger("tools")

#: Fields that are never accepted inside a tool argument payload.  The
#: strict Pydantic models already reject unknown keys; this list is a second,
#: independent guard that also inspects nested structures.
FORBIDDEN_ARGUMENT_KEYS = frozenset(
    {
        "code",
        "script",
        "python",
        "python_code",
        "sql",
        "query",
        "raw_sql",
        "shell",
        "bash",
        "command",
        "cmd",
        "exec",
        "eval",
        "compile",
        "import",
        "module",
        "path",
        "file",
        "filename",
        "filepath",
        "directory",
        "url",
        "endpoint",
        "open",
        "read",
        "write",
        "os",
        "subprocess",
        "pickle",
        "load",
        "dumps",
    }
)


@dataclass
class ToolContext:
    """Everything a tool handler is allowed to see."""

    db: Session
    settings: Settings
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    authorized_dataset_ids: tuple[str, ...] = ()
    approved_joins: tuple[dict[str, Any], ...] = ()
    trace: list[dict[str, Any]] = field(default_factory=list)
    token_budget: int = 0
    cost_budget_usd: float = 0.0
    spent_tokens: int = 0
    spent_cost_usd: float = 0.0
    cancelled: bool = False
    notes: list[str] = field(default_factory=list)

    def is_authorized(self, dataset_id: str) -> bool:
        return dataset_id in set(self.authorized_dataset_ids)

    def authorize(self, *dataset_ids: str) -> None:
        for dataset_id in dataset_ids:
            if not dataset_id:
                continue
            if not self.is_authorized(dataset_id):
                raise SecurityError(
                    f"dataset '{dataset_id}' is not authorised for this request",
                    details={"authorized_dataset_ids": list(self.authorized_dataset_ids)},
                )

    def add_note(self, note: str) -> None:
        if note not in self.notes:
            self.notes.append(note)


@dataclass
class ToolOutcome:
    """Structured result of a tool invocation."""

    data: dict[str, Any]
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    chart: dict[str, Any] | None = None
    export: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "data": self.data,
            "evidence": self.evidence,
        }
        if self.warnings:
            payload["warnings"] = self.warnings
        if self.chart:
            payload["chart"] = self.chart
        if self.export:
            payload["export"] = self.export
        return payload


Handler = Callable[[ToolContext, Any], ToolOutcome]


@dataclass
class RegisteredTool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    category: str = "general"
    requires_dataset: bool = True
    output_description: str = ""

    def json_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_model.model_json_schema(),
            "output": self.output_description,
        }


class ToolRegistry:
    """Finite, explicitly registered library of analysis tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        input_model: type[BaseModel],
        category: str = "general",
        requires_dataset: bool = True,
        output_description: str = "",
    ) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            if name in self._tools:
                raise RuntimeError(f"tool '{name}' is already registered")
            self._tools[name] = RegisteredTool(
                name=name,
                description=description,
                input_model=input_model,
                handler=handler,
                category=category,
                requires_dataset=requires_dataset,
                output_description=output_description,
            )
            return handler

        return decorator

    # -- introspection -----------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> RegisteredTool:
        tool = self._tools.get(name)
        if tool is None:
            raise SecurityError(
                f"tool '{name}' is not part of the allowlist",
                details={"available_tools": self.names()},
            )
        return tool

    def definitions(self) -> list[dict[str, Any]]:
        return [self._tools[name].json_schema() for name in self.names()]

    def catalogue(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "requires_dataset": tool.requires_dataset,
                "output": tool.output_description,
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    # -- execution ---------------------------------------------------------
    def validate_input(self, name: str, raw_input: Any) -> BaseModel:
        tool = self.get(name)
        if raw_input is None:
            raw_input = {}
        if not isinstance(raw_input, dict):
            raise ValidationError(f"arguments for '{name}' must be a JSON object")
        _reject_forbidden_keys(raw_input, name)
        try:
            return tool.input_model.model_validate(raw_input)
        except PydanticValidationError as exc:
            raise ValidationError(
                f"invalid arguments for tool '{name}': {_format_pydantic_error(exc)}",
                details={"tool": name},
            ) from exc

    def dispatch(
        self,
        ctx: ToolContext,
        name: str,
        raw_input: Any,
        *,
        round_index: int = 0,
    ) -> dict[str, Any]:
        """Validate, authorise and execute a tool call."""
        started = time.perf_counter()
        tool = self.get(name)
        arguments = self.validate_input(name, raw_input)
        self._enforce_dataset_scope(tool, arguments, ctx)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{name}")
        future = executor.submit(tool.handler, ctx, arguments)
        try:
            outcome = future.result(timeout=ctx.settings.tool_timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise ToolExecutionError(
                f"tool '{name}' exceeded the {ctx.settings.tool_timeout_seconds:g}s time limit",
                details={"tool": name},
            ) from exc
        except ValidationError:
            raise
        except SecurityError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            log.error("tool.failed", tool=name, error=str(exc))
            raise ToolExecutionError(
                f"tool '{name}' failed: {str(exc)[:300]}", details={"tool": name}
            ) from exc
        finally:
            executor.shutdown(wait=False)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        payload = outcome.to_dict()
        self._enforce_output_bounds(ctx, name, payload)
        payload["_meta"] = {
            "tool": name,
            "round": round_index,
            "elapsed_ms": elapsed_ms,
            "arguments": arguments.model_dump(mode="json"),
        }
        return payload

    # -- guards ------------------------------------------------------------
    def _enforce_dataset_scope(self, tool: RegisteredTool, arguments: BaseModel, ctx: ToolContext) -> None:
        if not tool.requires_dataset:
            return
        referenced: list[str] = []
        for field_name in ("dataset_id", "left_dataset_id", "right_dataset_id"):
            value = getattr(arguments, field_name, None)
            if isinstance(value, str) and value:
                referenced.append(value)
        if not referenced:
            return
        unknown = [d for d in referenced if not ctx.is_authorized(d)]
        if unknown:
            raise SecurityError(
                "the plan references datasets that are not authorised for this request",
                details={"unauthorized": unknown, "authorized": list(ctx.authorized_dataset_ids)},
            )

    def _enforce_output_bounds(self, ctx: ToolContext, name: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, default=str)
        size = len(encoded.encode("utf-8"))
        if size > ctx.settings.max_tool_result_bytes:
            raise ToolExecutionError(
                f"tool '{name}' produced {size} bytes which exceeds the "
                f"{ctx.settings.max_tool_result_bytes} byte limit; narrow the query",
                details={"tool": name, "bytes": size},
            )
        rows = _count_rows(payload)
        if rows is not None and rows > ctx.settings.max_tool_result_rows:
            raise ToolExecutionError(
                f"tool '{name}' returned {rows} rows which exceeds the "
                f"{ctx.settings.max_tool_result_rows} row limit",
                details={"tool": name, "rows": rows},
            )


def _count_rows(payload: dict[str, Any]) -> int | None:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return None
    for key in ("rows", "results", "ranked", "top", "bottom", "buckets", "pairs", "groups", "preview"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _reject_forbidden_keys(raw: dict[str, Any], tool_name: str) -> None:
    """Reject argument payloads that try to smuggle code / paths / SQL."""
    stack: list[Any] = [raw]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if not isinstance(key, str):
                    raise SecurityError(f"tool '{tool_name}' received a non-string argument key")
                lowered = key.lower()
                if lowered in FORBIDDEN_ARGUMENT_KEYS or lowered.startswith("__"):
                    raise SecurityError(
                        f"argument '{key}' is not permitted for tool '{tool_name}'",
                        details={"tool": tool_name, "key": key},
                    )
                stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)


def _format_pydantic_error(exc: PydanticValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors()[:8]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        message = error.get("msg", "invalid value")
        parts.append(f"{location or 'input'}: {message}")
    return "; ".join(parts)[:600]


registry = ToolRegistry()


def register_tool(
    name: str,
    *,
    description: str,
    input_model: type[BaseModel],
    category: str = "general",
    requires_dataset: bool = True,
    output_description: str = "",
) -> Callable[[Handler], Handler]:
    """Module level convenience wrapper around :meth:`ToolRegistry.register`."""
    return registry.register(
        name,
        description=description,
        input_model=input_model,
        category=category,
        requires_dataset=requires_dataset,
        output_description=output_description,
    )


def list_tool_definitions() -> list[dict[str, Any]]:
    return registry.definitions()


def tool_catalogue() -> list[dict[str, Any]]:
    return registry.catalogue()


def execute_tool(
    ctx: ToolContext,
    tool_name: str,
    tool_input: Any,
    *,
    round_index: int = 0,
) -> dict[str, Any]:
    return registry.dispatch(ctx, tool_name, tool_input, round_index=round_index)


def dataset_ids_in_arguments(arguments: Any) -> Sequence[str]:
    """Extract dataset references from a validated argument object."""
    ids: list[str] = []
    for field_name in ("dataset_id", "left_dataset_id", "right_dataset_id"):
        value = getattr(arguments, field_name, None)
        if isinstance(value, str) and value:
            ids.append(value)
    return ids


def ensure_iterable(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return value
    return [value]
