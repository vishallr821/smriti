from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from smriti.llm.exceptions import LLMRouterError, ProviderDownError
from smriti.llm.providers import GroqProvider
from smriti.llm.router import ModelRouter


class Person(BaseModel):
    name: str
    age: int


@pytest.mark.asyncio
async def test_fallback_to_ollama_on_timeout():
    groq = AsyncMock()
    ollama = AsyncMock()
    groq.complete = AsyncMock(side_effect=TimeoutError("timeout"))
    ollama.complete = AsyncMock(return_value=Person(name="John", age=30))
    router = ModelRouter(providers={"groq_8b": groq, "groq_70b": groq, "ollama": ollama})

    result = await router.call("intent_classification", "Extract John", Person)
    assert result.name == "John"
    assert groq.complete.await_count == 1
    assert ollama.complete.await_count == 1
    assert router.last_provider_used == "ollama"


@pytest.mark.asyncio
async def test_schema_validation_retries_on_invalid_json(monkeypatch):
    provider = GroqProvider("llama-3.1-8b-instant")
    call_count = {"n": 0}

    class _Resp:
        def __init__(self, content: str):
            self.content = content

    async def _fake_invoke(prompt: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp("{invalid")
        return _Resp('{"name":"John","age":30}')

    class _FakeChat:
        def __init__(self, *args, **kwargs):
            pass

        ainvoke = staticmethod(_fake_invoke)

    monkeypatch.setattr("smriti.llm.providers.ChatGroq", _FakeChat)
    result = await provider.complete("Extract", Person)
    assert result.name == "John"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_schema_mismatch_retries(monkeypatch):
    provider = GroqProvider("llama-3.1-8b-instant")
    call_count = {"n": 0}

    class _Resp:
        def __init__(self, content: str):
            self.content = content

    async def _fake_invoke(prompt: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp('{"full_name":"John"}')
        return _Resp('{"name":"John","age":30}')

    class _FakeChat:
        def __init__(self, *args, **kwargs):
            pass

        ainvoke = staticmethod(_fake_invoke)

    monkeypatch.setattr("smriti.llm.providers.ChatGroq", _FakeChat)
    result = await provider.complete("Extract", Person)
    assert result.age == 30
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_both_fail_raises_router_error():
    groq = AsyncMock()
    ollama = AsyncMock()
    groq.complete = AsyncMock(side_effect=TimeoutError("timeout"))
    ollama.complete = AsyncMock(side_effect=ProviderDownError("down"))
    router = ModelRouter(providers={"groq_8b": groq, "groq_70b": groq, "ollama": ollama})

    with pytest.raises(LLMRouterError):
        await router.call("intent_classification", "Extract John", Person)


@pytest.mark.asyncio
async def test_cache_hit_on_second_call(monkeypatch, tmp_path):
    monkeypatch.setattr("smriti.llm.router.settings.demo_cache", True)
    monkeypatch.setattr("smriti.llm.cache.CACHE_DIR", tmp_path / "llm-test-cache")

    groq = AsyncMock()
    ollama = AsyncMock()
    groq.complete = AsyncMock(return_value=Person(name="John", age=30))
    ollama.complete = AsyncMock(return_value=Person(name="Alt", age=40))
    router = ModelRouter(providers={"groq_8b": groq, "groq_70b": groq, "ollama": ollama})

    prompt = "Extract John cache-test unique"
    r1 = await router.call("intent_classification", prompt, Person)
    r2 = await router.call("intent_classification", prompt, Person)
    assert r1.name == "John"
    assert r2.name == "John"
    assert groq.complete.await_count == 1
