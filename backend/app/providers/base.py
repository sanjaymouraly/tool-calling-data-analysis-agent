"""Provider abstraction.

A provider is anything that can turn a natural-language question plus a
dataset context into a *structured plan* (and optionally a grounded
narrative).  Six adapters ship with the application:

``free``       deterministic, API-free, works offline
``openai``     OpenAI platform API (an API key - not a ChatGPT subscription)
``anthropic``  Anthropic Claude API
``openrouter`` OpenRouter
``custom``     any OpenAI-compatible endpoint (vLLM, LM Studio, ...)
``ollama``     locally hosted models

Whatever the provider, the output is always the same shape and is always
validated against the tool registry before a single tool runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ProviderError  # noqa: F401  (re-exported for adapters)


@dataclass
class DatasetContext:
    """The (bounded) view of a dataset that is handed to a model."""

    id: str
    name: str
    row_count: int
    column_count: int
    columns: list[dict[str, Any]] = field(default_factory=list)
    date_ranges: dict[str, dict[str, str | None]] = field(default_factory=dict)
    latest_periods: dict[str, str] = field(default_factory=dict)
    currency: str = "USD"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": self.columns,
            "date_ranges": self.date_ranges,
            "latest_periods": self.latest_periods,
            "currency": self.currency,
        }


@dataclass
class ProviderContext:
    """Everything a provider needs to produce a plan."""

    question: str
    datasets: list[DatasetContext]
    tools: list[dict[str, Any]]
    max_rounds: int = 6
    previous_messages: list[dict[str, str]] = field(default_factory=list)

    def dataset(self, dataset_id: str) -> DatasetContext | None:
        for item in self.datasets:
            if item.id == dataset_id:
                return item
        return None

    def prompt_block(self) -> str:
        import json

        return json.dumps(
            {
                "question": self.question,
                "datasets": [d.to_prompt_dict() for d in self.datasets],
                "tools": self.tools,
            },
            indent=2,
            default=str,
        )


@dataclass
class ProviderResult:
    """The result of asking a provider for a plan."""

    plan: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    mode: str = "plan"
    notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderInfo:
    """Static description of a provider, used by the settings wizard."""

    name: str
    label: str
    requires_key: bool
    default_base_url: str
    default_model: str
    supports_native_tools: bool
    supports_model_listing: bool
    notes: str = ""


class BaseProvider:
    """Base class for all provider adapters."""

    name: str = "base"
    info: ProviderInfo

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.api_key: str = options.get("api_key") or ""
        self.base_url: str = (options.get("base_url") or "").rstrip("/")
        self.model: str = options.get("model") or ""

    # -- capabilities ------------------------------------------------------
    @property
    def requires_key(self) -> bool:
        return self.info.requires_key

    # -- API ---------------------------------------------------------------
    async def plan(self, context: ProviderContext) -> ProviderResult:
        raise NotImplementedError

    async def narrate(self, context: ProviderContext, observations: list[dict[str, Any]]) -> str:
        """Optional narrative generation grounded in tool observations."""
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        return []

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "model": self.model}

    # -- helpers -----------------------------------------------------------
    def resolve_model(self) -> str:
        if self.model:
            return self.model
        return self.info.default_model

    def masked_key(self) -> str | None:
        if not self.api_key:
            return None
        if len(self.api_key) <= 8:
            return "***" + self.api_key[-2:]
        return f"{self.api_key[:3]}***{self.api_key[-4:]}"
