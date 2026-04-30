"""LLM model router with fallback and optional disk cache."""

from __future__ import annotations

import time
from typing import Any

import structlog
from pydantic import BaseModel

from smriti.config import settings

from .cache import build_cache_key, get_cached, set_cached
from .exceptions import LLMRouterError, ProviderDownError, RateLimitError
from .providers import GroqProvider, LLMProvider, OllamaProvider

ROLE_TO_MODELS = {
    "ingestion_extraction": ("groq_8b", "ollama"),
    "normalization": ("groq_8b", "ollama"),
    "intent_classification": ("groq_8b", "ollama"),
    "synthesis": ("groq_70b", "ollama"),
}

MODEL_NAME_MAP = {
    "groq_70b": "llama-3.3-70b-versatile",
    "groq_8b": "llama-3.1-8b-instant",
    "ollama": "llama3.2:3b",
}

logger = structlog.get_logger("llm_router")
_router: "ModelRouter | None" = None


class ModelRouter:
    def __init__(self, providers: dict[str, LLMProvider] | None = None) -> None:
        self.providers = providers or {
            "groq_70b": GroqProvider(MODEL_NAME_MAP["groq_70b"]),
            "groq_8b": GroqProvider(MODEL_NAME_MAP["groq_8b"]),
            "ollama": OllamaProvider(MODEL_NAME_MAP["ollama"]),
        }
        self.last_provider_used: str | None = None

    async def call(
        self,
        role: str,
        prompt: str,
        schema: type[BaseModel],
        timeout: float = 5.0,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        if role not in ROLE_TO_MODELS:
            raise LLMRouterError(f"Unknown role: {role}")

        cache_key = build_cache_key(role, prompt, schema.__name__)
        if settings.demo_cache:
            cached = get_cached(cache_key)
            if cached is not None:
                self.last_provider_used = "cache"
                logger.info(
                    "llm_call",
                    role=role,
                    provider="cache",
                    latency_ms=0,
                    success=True,
                    retry_count=0,
                )
                return schema.model_validate(cached)

        primary_name, secondary_name = ROLE_TO_MODELS[role]
        providers_to_try = [primary_name, secondary_name]
        errors: list[str] = []
        for idx, provider_name in enumerate(providers_to_try):
            provider = self.providers[provider_name]
            started = time.perf_counter()
            try:
                result = await provider.complete(
                    prompt=prompt,
                    schema=schema,
                    temperature=temperature,
                    timeout=timeout,
                    max_tokens=max_tokens,
                )
                latency_ms = int((time.perf_counter() - started) * 1000)
                self.last_provider_used = provider_name
                logger.info(
                    "llm_call",
                    role=role,
                    provider=provider_name,
                    latency_ms=latency_ms,
                    success=True,
                    retry_count=idx,
                )
                if settings.demo_cache:
                    set_cached(cache_key, result.model_dump())
                return result
            except (TimeoutError, RateLimitError, ProviderDownError) as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                logger.warning(
                    "llm_call",
                    role=role,
                    provider=provider_name,
                    latency_ms=latency_ms,
                    success=False,
                    retry_count=idx,
                    error=str(exc),
                )
                errors.append(f"{provider_name}: {exc}")
                continue
            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                logger.warning(
                    "llm_call",
                    role=role,
                    provider=provider_name,
                    latency_ms=latency_ms,
                    success=False,
                    retry_count=idx,
                    error=str(exc),
                )
                errors.append(f"{provider_name}: {exc}")
                continue

        raise LLMRouterError(f"All providers failed for role={role}. Errors: {' | '.join(errors)}")


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
