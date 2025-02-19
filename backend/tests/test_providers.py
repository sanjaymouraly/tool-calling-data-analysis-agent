"""Provider adapter tests.

The HTTP layer is mocked so the tests are deterministic and never touch the
network.  The point of these tests is the *contract* of an adapter: a plan
in, a validated plan out, and a clean error when the provider misbehaves.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.providers.base import ProviderContext, ProviderError
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.registry import PROVIDER_INFO, build_provider, provider_status, resolve_options


def _context() -> ProviderContext:
    from app.providers.base import DatasetContext

    dataset = DatasetContext(
        id="ds-1",
        name="Retail Orders",
        row_count=5018,
        column_count=14,
        columns=[
            {"name": "Revenue", "type": "numeric", "role": "money"},
            {"name": "Order_Date", "type": "date", "role": "date"},
        ],
        date_ranges={"Order_Date": {"min": "2023-01-01", "max": "2024-12-31"}},
        latest_periods={"Order_Date": "2024-12"},
    )
    return ProviderContext(
        question="What were monthly sales?",
        datasets=[dataset],
        tools=[{"name": "time_series", "description": "d", "category": "query"}],
    )


def _mock_provider(handler, **kwargs) -> OpenAICompatProvider:
    """Return a provider whose HTTP calls are served by ``handler``."""
    original = httpx.AsyncClient

    def factory(*args, **client_kwargs):
        client_kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **client_kwargs)

    httpx.AsyncClient = factory  # type: ignore[assignment]
    try:
        provider = OpenAICompatProvider(
            name="openai",
            info=PROVIDER_INFO["openai"],
            api_key="sk-test",
            base_url="https://api.example.invalid/v1",
            model="test-model",
            **kwargs,
        )
        provider._restore = factory  # type: ignore[attr-defined]
        return provider
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]


class _Patch:
    """Context manager that keeps httpx.AsyncClient patched for its lifetime."""

    def __init__(self, handler):
        self.handler = handler
        self.original = httpx.AsyncClient

    def __enter__(self):
        original = self.original

        def factory(*args, **client_kwargs):
            client_kwargs["transport"] = httpx.MockTransport(self.handler)
            return original(*args, **client_kwargs)

        httpx.AsyncClient = factory  # type: ignore[assignment]
        return self

    def __exit__(self, *exc):
        httpx.AsyncClient = self.original  # type: ignore[assignment]
        return False


def _chat_completion(content: str) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
    }


class TestOpenAICompat:
    @pytest.mark.asyncio
    async def test_plan_is_parsed(self):
        plan = {"steps": [{"tool": "time_series", "input": {"dataset_id": "ds-1"}}]}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["model"] == "test-model"
            assert body["response_format"] == {"type": "json_object"}
            return httpx.Response(200, json=_chat_completion(json.dumps(plan)))

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
                model="test-model",
            )
            result = await provider.plan(_context())
        assert result.plan["steps"][0]["tool"] == "time_series"
        assert result.usage["total_tokens"] == 165
        assert result.usage["estimated_cost_usd"] >= 0

    @pytest.mark.asyncio
    async def test_fenced_json_is_accepted(self):
        plan = {"steps": []}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_chat_completion(f"```json\n{json.dumps(plan)}\n```"))

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
            )
            result = await provider.plan(_context())
        assert result.plan["steps"] == []

    @pytest.mark.asyncio
    async def test_http_error_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-bad",
                base_url="https://api.example.invalid/v1",
            )
            with pytest.raises(ProviderError) as excinfo:
                await provider.plan(_context())
        assert "401" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_malformed_json_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_chat_completion("not json at all"))

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
            )
            with pytest.raises(ProviderError):
                await provider.plan(_context())

    @pytest.mark.asyncio
    async def test_model_listing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
            )
            models = await provider.list_models()
        assert models == ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_timeout_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
                timeout=0.1,
            )
            with pytest.raises(ProviderError) as excinfo:
                await provider.plan(_context())
        assert "timed out" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_network_failure_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="openai",
                info=PROVIDER_INFO["openai"],
                api_key="sk-test",
                base_url="https://api.example.invalid/v1",
            )
            with pytest.raises(ProviderError):
                await provider.plan(_context())

    @pytest.mark.asyncio
    async def test_ollama_uses_the_v1_prefix(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json=_chat_completion(json.dumps({"steps": []})))

        with _Patch(handler):
            provider = OpenAICompatProvider(
                name="ollama",
                info=PROVIDER_INFO["ollama"],
                base_url="http://localhost:11434",
                model="gemma3:1b",
            )
            await provider.plan(_context())
        assert seen["url"] == "http://localhost:11434/v1/chat/completions"


class TestAnthropic:
    @pytest.mark.asyncio
    async def test_plan_is_parsed(self):
        from app.providers.anthropic import AnthropicProvider

        plan = {"steps": [{"tool": "compute_kpi", "input": {}}]}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "sk-ant-test"
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": json.dumps(plan)}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

        with _Patch(handler):
            provider = AnthropicProvider(
                api_key="sk-ant-test",
                base_url="https://api.anthropic.invalid",
                model="claude-3-5-sonnet-latest",
            )
            result = await provider.plan(_context())
        assert result.plan["steps"][0]["tool"] == "compute_kpi"
        assert result.usage["prompt_tokens"] == 10


class TestFreeProvider:
    @pytest.mark.asyncio
    async def test_free_provider_needs_no_key(self):
        from app.providers.free import FreeProvider

        provider = FreeProvider()
        result = await provider.plan(_context())
        assert result.plan["steps"]
        assert result.usage["total_tokens"] == 0
        assert (await provider.test_connection())["ok"] is True

    @pytest.mark.asyncio
    async def test_free_provider_refuses_to_narrate(self):
        from app.providers.free import FreeProvider

        with pytest.raises(ProviderError):
            await FreeProvider().narrate(_context(), [])


class TestProviderRegistry:
    def test_all_providers_can_be_built(self):
        for name in PROVIDER_INFO:
            provider = build_provider(name, {"api_key": "x", "base_url": "http://x/v1", "model": "m"})
            assert provider.name == name

    def test_free_provider_needs_no_key(self):
        assert build_provider("free").name == "free"

    def test_unknown_provider_falls_back_to_free(self):
        assert build_provider("does-not-exist").name == "free"

    def test_status_masks_the_key(self, db):
        status = provider_status(db, "openai")
        assert "api_key" not in status
        assert status["masked_key"] is None or "*" in status["masked_key"] or "..." in status["masked_key"]

    def test_environment_options_are_used(self, db, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-env")
        options = resolve_options(db, "openai")
        assert options["api_key"] == "sk-env"

    def test_stored_configuration_wins_over_the_environment(self, db, monkeypatch):
        from app.db.models import ProviderConfig

        monkeypatch.setattr(settings, "openai_api_key", "sk-env")
        db.add(
            ProviderConfig(
                provider="openai",
                api_key_encrypted=encrypt_secret("sk-stored"),
                model="stored-model",
            )
        )
        db.commit()
        options = resolve_options(db, "openai")
        assert options["api_key"] == "sk-stored"
        assert options["model"] == "stored-model"


class TestSecretStorage:
    def test_encryption_round_trip(self):
        secret = "sk-super-secret"
        encrypted = encrypt_secret(secret)
        assert secret not in encrypted
        assert decrypt_secret(encrypted) == secret

    def test_masking(self):
        assert "sk-super-secret" not in mask_secret("sk-super-secret")

    def test_wrong_key_cannot_decrypt(self):
        from app.core.errors import ValidationError

        encrypted = encrypt_secret("value")
        # corrupt the payload
        with pytest.raises(ValidationError):
            decrypt_secret(encrypted[:-4] + "AAAA")


class TestPricing:
    def test_known_model(self):
        from app.providers.pricing import estimate_cost

        result = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        assert result["price_known"] is True
        assert result["estimated_cost_usd"] > 0

    def test_unknown_model_is_flagged(self):
        from app.providers.pricing import estimate_cost

        result = estimate_cost("mystery-model-9000", 1000, 1000)
        assert result["price_known"] is False
        assert result["estimated_cost_usd"] == 0.0
