"""Provider implementations for Groq and Ollama."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from smriti.config import settings

from .exceptions import ProviderDownError, RateLimitError, SchemaValidationError


class LLMProvider(ABC):
    model_name: str

    def __init__(self, model_name: str, max_tokens: int = 2000) -> None:
        self.model_name = model_name
        self.max_tokens = max_tokens

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        timeout: float = 5.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        raise NotImplementedError


class GroqProvider(LLMProvider):
    async def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        timeout: float = 5.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        llm = ChatGroq(
            model=self.model_name,
            groq_api_key=settings.groq_api_key,
            temperature=temperature,
            max_tokens=max_tokens or self.max_tokens,
            timeout=timeout,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        attempted_prompt = prompt
        last_validation_error = ""
        for _ in range(2):
            try:
                response = await llm.ainvoke(attempted_prompt)
                text = getattr(response, "content", response)
                parsed = json.loads(text if isinstance(text, str) else str(text))
                return schema.model_validate(parsed)
            except ValidationError as exc:
                last_validation_error = str(exc)
                attempted_prompt = (
                    f"{prompt}\n\nPrevious output failed schema validation: {last_validation_error}\n"
                    "Return strict JSON matching the schema."
                )
            except json.JSONDecodeError as exc:
                last_validation_error = str(exc)
                attempted_prompt = (
                    f"{prompt}\n\nPrevious output was not valid JSON: {last_validation_error}\n"
                    "Return valid JSON only."
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError("Groq timeout") from exc
            except Exception as exc:
                self._raise_provider_error(exc)
        raise SchemaValidationError(f"Groq schema validation failed: {last_validation_error}")

    @staticmethod
    def _raise_provider_error(exc: Exception) -> None:
        message = str(exc).lower()
        if "rate limit" in message or "429" in message:
            raise RateLimitError(str(exc)) from exc
        if "connection" in message or "503" in message or "unavailable" in message:
            raise ProviderDownError(str(exc)) from exc
        raise ProviderDownError(str(exc)) from exc


class OllamaProvider(LLMProvider):
    async def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        timeout: float = 5.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        attempted_prompt = prompt
        last_validation_error = ""
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{settings.ollama_base_url}/api/generate",
                        json={
                            "model": self.model_name,
                            "prompt": attempted_prompt,
                            "format": "json",
                            "stream": False,
                            "options": {
                                "temperature": temperature,
                                "num_predict": max_tokens or self.max_tokens,
                            },
                        },
                    )
                if resp.status_code == 429:
                    raise RateLimitError("Ollama rate limited")
                if resp.status_code >= 500:
                    raise ProviderDownError(f"Ollama unavailable: {resp.status_code}")
                resp.raise_for_status()
                body = resp.json()
                response_text = body.get("response", "{}")
                parsed = json.loads(response_text)
                return schema.model_validate(parsed)
            except ValidationError as exc:
                last_validation_error = str(exc)
                attempted_prompt = (
                    f"{prompt}\n\nPrevious output failed schema validation: {last_validation_error}\n"
                    "Return strict JSON matching the schema."
                )
            except json.JSONDecodeError as exc:
                last_validation_error = str(exc)
                attempted_prompt = (
                    f"{prompt}\n\nPrevious output was not valid JSON: {last_validation_error}\n"
                    "Return valid JSON only."
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError("Ollama timeout") from exc
            except (RateLimitError, ProviderDownError):
                raise
            except httpx.HTTPError as exc:
                raise ProviderDownError(str(exc)) from exc
        raise SchemaValidationError(f"Ollama schema validation failed: {last_validation_error}")
