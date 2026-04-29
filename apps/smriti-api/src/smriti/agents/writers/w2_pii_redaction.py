"""W2 PII redaction + injection guard."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from smriti.db.connection import get_pool
from smriti.db.encryption import encrypt_field
from smriti.schemas.clinical import RawClinicalEntity
from smriti.security import InjectionGuard, PIIRedactor

logger = structlog.get_logger("w2_pii")


class InjectionAbortError(RuntimeError):
    pass


@dataclass(slots=True)
class RedactionResult:
    sanitized_entities: list[RawClinicalEntity]
    sanitized_text: str | None
    redaction_map: dict[str, str]
    injection_detected: bool


class PIIRedactionAgent:
    def __init__(self) -> None:
        self.injection_guard = InjectionGuard()
        self.pii_redactor = PIIRedactor()

    async def _log_injection(self, reason: str, severity: str, source_provider: str, payload: str) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_guard_events (agent, event_type, details, created_at)
                VALUES ($1, $2, $3::jsonb, $4)
                """,
                "w2_pii_redaction",
                "injection_detected",
                json.dumps({"reason": reason, "severity": severity}),
                datetime.now(UTC),
            )
            if severity == "high":
                await conn.execute(
                    """
                    INSERT INTO quarantine (source_provider, raw_payload, reason, detected_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    source_provider,
                    payload,
                    f"injection:{reason}",
                    datetime.now(UTC),
                )

    async def _persist_redaction_map(self, abha_id: str, redaction_map: dict[str, str]) -> None:
        if not redaction_map:
            return
        pool = await get_pool()
        async with pool.acquire() as conn:
            for original, placeholder in redaction_map.items():
                await conn.execute(
                    """
                    INSERT INTO redaction_keys (abha_id, placeholder, real_value_enc, created_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    abha_id,
                    placeholder,
                    encrypt_field(original),
                    datetime.now(UTC),
                )

    async def run(
        self, entities: list[RawClinicalEntity], raw_text: str | None = None, abha_id: str = "unknown"
    ) -> RedactionResult:
        start = time.perf_counter()
        logger.info("entry", agent="w2", entity_count=len(entities))
        merged_map: dict[str, str] = {}
        injection_detected = False
        sanitized_text = raw_text
        try:
            if raw_text:
                inj = self.injection_guard.detect(raw_text)
                if inj.detected:
                    injection_detected = True
                    await self._log_injection(inj.reason or "detected", inj.severity, entities[0].source_provider if entities else "unknown", raw_text)
                    if inj.severity == "high":
                        raise InjectionAbortError(inj.reason or "high_severity_injection")
                redacted_text = self.pii_redactor.redact(raw_text)
                sanitized_text = redacted_text.redacted_text
                merged_map.update(redacted_text.redaction_map)

            sanitized_entities: list[RawClinicalEntity] = []
            for entity in entities:
                redacted = self.pii_redactor.redact(entity.raw_value)
                merged_map.update(redacted.redaction_map)
                sanitized_entities.append(entity.model_copy(update={"raw_value": redacted.redacted_text}))

            await self._persist_redaction_map(abha_id, merged_map)
            return RedactionResult(
                sanitized_entities=sanitized_entities,
                sanitized_text=sanitized_text,
                redaction_map=merged_map,
                injection_detected=injection_detected,
            )
        finally:
            logger.info("exit", agent="w2", latency_ms=int((time.perf_counter() - start) * 1000))
