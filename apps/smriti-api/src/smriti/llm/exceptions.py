"""Custom exceptions for LLM providers and router."""

from __future__ import annotations


class LLMRouterError(RuntimeError):
    """Raised when router cannot complete a call with any configured provider."""


class RateLimitError(RuntimeError):
    """Raised when provider enforces request throttling/rate limits."""


class ProviderDownError(RuntimeError):
    """Raised when provider endpoint is unavailable."""


class SchemaValidationError(RuntimeError):
    """Raised when provider output fails schema validation after retries."""
