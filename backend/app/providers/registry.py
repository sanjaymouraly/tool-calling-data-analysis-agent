"""Provider factory.

Resolves a provider name into a configured adapter.  Credentials come from
(1) the database configuration table, (2) environment variables, in that
order.  Nothing is ever logged in clear text.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.crypto import decrypt_secret, key_hint, mask_secret
from ..db.models import ProviderConfig
from .anthropic import AnthropicProvider
from .base import BaseProvider, ProviderInfo
from .free import FreeProvider
from .openai_compat import OpenAICompatProvider

PROVIDER_ORDER = ["free", "openai", "anthropic", "openrouter", "custom", "ollama"]

PROVIDER_INFO: dict[str, ProviderInfo] = {
    "free": ProviderInfo(
        name="free",
        label="Free guided mode (no API key)",
        requires_key=False,
        default_base_url="",
        default_model="deterministic-rule-engine",
        supports_native_tools=False,
        supports_model_listing=False,
        notes="Deterministic rule-based analysis and a visual query builder. Works completely offline.",
    ),
    "openai": ProviderInfo(
        name="openai",
        label="OpenAI API",
        requires_key=True,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        supports_native_tools=True,
        supports_model_listing=True,
        notes=(
            "Uses an OpenAI platform API key. A ChatGPT Plus/Pro subscription does NOT include API access "
            "and cannot be used here."
        ),
    ),
    "anthropic": ProviderInfo(
        name="anthropic",
        label="Anthropic Claude API",
        requires_key=True,
        default_base_url="https://api.anthropic.com",
        default_model="claude-3-5-sonnet-latest",
        supports_native_tools=True,
        supports_model_listing=True,
        notes="Requires an Anthropic console API key (not a claude.ai subscription).",
    ),
    "openrouter": ProviderInfo(
        name="openrouter",
        label="OpenRouter",
        requires_key=True,
        default_base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        supports_native_tools=True,
        supports_model_listing=True,
        notes="One key, many models. Usage is billed by the model you choose.",
    ),
    "custom": ProviderInfo(
        name="custom",
        label="Custom OpenAI-compatible endpoint",
        requires_key=False,
        default_base_url="",
        default_model="",
        supports_native_tools=True,
        supports_model_listing=True,
        notes=(
            "Any endpoint that speaks /v1/chat/completions: vLLM, LM Studio, LiteLLM, Together, Groq, "
            "a corporate gateway, and so on."
        ),
    ),
    "ollama": ProviderInfo(
        name="ollama",
        label="Ollama (local)",
        requires_key=False,
        default_base_url="http://localhost:11434",
        default_model="gemma3:1b",
        supports_native_tools=True,
        supports_model_listing=True,
        notes="Runs models on your own machine. No data leaves the host and no key is needed.",
    ),
}


def env_options(provider: str) -> dict[str, Any]:
    """Environment-based configuration for a provider."""
    if provider == "openai":
        return {
            "api_key": settings.openai_api_key,
            "base_url": settings.openai_base_url,
            "model": settings.openai_model,
        }
    if provider == "anthropic":
        return {
            "api_key": settings.anthropic_api_key,
            "base_url": settings.anthropic_base_url,
            "model": settings.anthropic_model,
        }
    if provider == "openrouter":
        return {
            "api_key": settings.openrouter_api_key,
            "base_url": settings.openrouter_base_url,
            "model": settings.openrouter_model,
        }
    if provider == "custom":
        return {
            "api_key": settings.custom_api_key,
            "base_url": settings.custom_base_url,
            "model": settings.custom_model,
        }
    if provider == "ollama":
        return {
            "api_key": "",
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
        }
    return {}


def stored_config(db: Session, provider: str) -> ProviderConfig | None:
    return db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider)).scalars().first()


def resolve_options(
    db: Session | None, provider: str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Merge (in order of precedence) overrides, stored config and environment."""
    options: dict[str, Any] = dict(env_options(provider))
    if db is not None and provider != "free":
        config = stored_config(db, provider)
        if config is not None:
            if config.base_url:
                options["base_url"] = config.base_url
            if config.model:
                options["model"] = config.model
            if config.api_key_encrypted:
                try:
                    options["api_key"] = decrypt_secret(config.api_key_encrypted)
                except Exception:  # pragma: no cover - key rotation
                    options["api_key"] = ""
    for key, value in (overrides or {}).items():
        if value not in (None, ""):
            options[key] = value
    return options


def build_provider(provider: str, options: dict[str, Any] | None = None) -> BaseProvider:
    """Instantiate a provider adapter."""
    name = (provider or "free").strip().lower()
    if name not in PROVIDER_INFO:
        # An unknown provider is never silently treated as a hosted API: the
        # request falls back to the deterministic free mode instead.
        return FreeProvider(**dict(options or {}))
    info = PROVIDER_INFO[name]
    opts = dict(options or {})

    if name == "free":
        return FreeProvider(**opts)
    if name == "anthropic":
        return AnthropicProvider(
            api_key=opts.get("api_key", ""),
            base_url=opts.get("base_url", "") or info.default_base_url,
            model=opts.get("model", "") or info.default_model,
            timeout=60.0,
        )
    if name == "ollama":
        return OpenAICompatProvider(
            name="ollama",
            info=info,
            api_key=opts.get("api_key", ""),
            base_url=opts.get("base_url", "") or info.default_base_url,
            model=opts.get("model", "") or info.default_model,
            timeout=settings.ollama_timeout_seconds,
            extra_headers={},
            json_mode=bool(opts.get("json_mode", True)),
        )
    if name == "openrouter":
        return OpenAICompatProvider(
            name="openrouter",
            info=info,
            api_key=opts.get("api_key", ""),
            base_url=opts.get("base_url", "") or info.default_base_url,
            model=opts.get("model", "") or info.default_model,
            timeout=60.0,
            extra_headers={
                "HTTP-Referer": "https://github.com/tool-using-data-analyst",
                "X-Title": "Tool-Calling Data Analysis Agent",
            },
        )
    return OpenAICompatProvider(
        name=name,
        info=info,
        api_key=opts.get("api_key", ""),
        base_url=opts.get("base_url", "") or info.default_base_url,
        model=opts.get("model", "") or info.default_model,
        timeout=60.0,
        json_mode=bool(opts.get("json_mode", True)),
    )


def get_provider(
    db: Session | None,
    provider: str,
    overrides: dict[str, Any] | None = None,
) -> BaseProvider:
    options = resolve_options(db, provider, overrides)
    return build_provider(provider, options)


def provider_status(db: Session | None, provider: str) -> dict[str, Any]:
    """Describe how a provider is currently configured (never the secret)."""
    info = PROVIDER_INFO.get(provider, PROVIDER_INFO["free"])
    options = resolve_options(db, provider)
    key = options.get("api_key") or ""
    return {
        "provider": provider,
        "label": info.label,
        "requires_key": info.requires_key,
        "base_url": options.get("base_url") or info.default_base_url,
        "model": options.get("model") or info.default_model,
        "has_key": bool(key),
        "masked_key": mask_secret(key),
        "key_hint": key_hint(key),
        "supports_native_tools": info.supports_native_tools,
        "supports_model_listing": info.supports_model_listing,
        "notes": info.notes,
    }
