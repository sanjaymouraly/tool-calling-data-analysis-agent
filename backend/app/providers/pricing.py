"""Model pricing.

The numbers below are **placeholders** that the operator can override per
provider in the settings screen.  They exist so the application can show an
*estimate* of the cost of a request; they are not a price list and must not
be presented as one.  Unknown models are billed at zero and flagged as
"price unknown" so the estimate is never silently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float
    source: str = "configurable default (not a verified price list)"


#: Default placeholder prices.  Replace them with your own numbers - or with
#: the real prices of your provider - before relying on the cost estimate.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "o4-mini": ModelPrice(1.10, 4.40),
    "claude-3-5-sonnet": ModelPrice(3.00, 15.00),
    "claude-3-5-haiku": ModelPrice(0.80, 4.00),
    "claude-3-haiku": ModelPrice(0.25, 1.25),
    "mistral-small": ModelPrice(0.20, 0.60),
    "llama-3.1-8b": ModelPrice(0.05, 0.08),
    "gemma": ModelPrice(0.0, 0.0),
    "llama": ModelPrice(0.0, 0.0),
    "qwen": ModelPrice(0.0, 0.0),
    "deepseek": ModelPrice(0.27, 1.10),
}


def price_for(model: str | None) -> tuple[ModelPrice, bool]:
    """Return ``(price, known)`` for a model name."""
    if not model:
        return ModelPrice(0.0, 0.0), False
    lowered = model.lower()
    for prefix, price in DEFAULT_PRICES.items():
        if prefix in lowered:
            return price, True
    return ModelPrice(0.0, 0.0), False


def estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    """Estimate the USD cost of a provider call."""
    price, known = price_for(model)
    cost = (prompt_tokens / 1_000_000) * price.input_per_mtok + (
        completion_tokens / 1_000_000
    ) * price.output_per_mtok
    return {
        "estimated_cost_usd": round(cost, 6),
        "price_known": known,
        "input_per_mtok": price.input_per_mtok,
        "output_per_mtok": price.output_per_mtok,
        "source": price.source,
    }
