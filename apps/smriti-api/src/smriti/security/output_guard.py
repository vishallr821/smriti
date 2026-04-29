"""Outbound payload guard to prevent PII leakage to LLM providers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from pydantic import BaseModel, ValidationError

from smriti.db.connection import get_pool
from smriti.security.pii_redactor import PIIRedactor


class OutputGuard:
    def __init__(self) -> None:
        registry = RecognizerRegistry(supported_languages=["en"])
        self.analyzer = AnalyzerEngine(registry=registry, nlp_engine=None, supported_languages=["en"])
        self.redactor = PIIRedactor()
        self.analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="IN_AADHAAR",
                patterns=[Pattern("aadhaar", r"\b\d{12}\b", 1.0)],
            )
        )

    def validate_schema(self, payload: Any, schema: type[BaseModel]) -> bool:
        try:
            schema.model_validate(payload)
            return True
        except ValidationError:
            return False

    async def _log_guard_event(self, details: dict) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_guard_events (agent, event_type, details, created_at)
                VALUES ($1, $2, $3::jsonb, $4)
                """,
                "output_guard",
                "pii_leak_blocked",
                str(details).replace("'", '"'),
                datetime.now(UTC),
            )

    def audit_outbound_payload(self, payload: str) -> bool:
        results = self.analyzer.analyze(
            text=payload,
            language="en",
            entities=["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "IN_AADHAAR"],
        )
        if not results:
            return True

        details = {
            "count": len(results),
            "entities": [r.entity_type for r in results],
        }
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._log_guard_event(details))
            else:
                asyncio.run(self._log_guard_event(details))
        except Exception:
            # Guard verdict still blocks even if event logging fails.
            pass
        return False
