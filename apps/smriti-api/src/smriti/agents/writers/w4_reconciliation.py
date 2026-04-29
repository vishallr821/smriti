"""W4 deterministic reconciliation agent."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from rapidfuzz import fuzz

from smriti.db.connection import get_pool
from smriti.schemas.clinical import NormalizedClinicalEntity, ReconciliationResult

logger = structlog.get_logger("w4_reconcile")


class ReconciliationAgent:
    async def run(self, abha_id: str, entities: list[NormalizedClinicalEntity]) -> ReconciliationResult:
        start = time.perf_counter()
        logger.info("entry", agent="w4", entity_count=len(entities), abha_id=abha_id)
        result = ReconciliationResult()
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                for entity in entities:
                    table = {
                        "condition": "conditions",
                        "medication": "medications",
                        "observation": "observations",
                        "allergy": "allergies",
                    }[entity.entity_type]
                    rows = await conn.fetch(
                        f"SELECT * FROM {table} WHERE abha_id = $1",
                        abha_id,
                    )
                    # Conflict detection runs before merge: a code match with a
                    # contradicting clinical status (e.g. active allergy vs. NKA)
                    # is a clinical conflict, not a silent merge.
                    conflict = self._detect_conflict(entity, rows)
                    if conflict is not None:
                        result.conflicts.append(conflict)
                        continue

                    exact_match = self._find_exact(entity, rows)
                    if exact_match is not None:
                        result.merges.append({"entity": entity.model_dump(), "existing_id": str(exact_match["id"]), "strategy": "keep_latest_source"})
                        continue
                    fuzzy_match = self._find_fuzzy(entity.display_name, rows)
                    if fuzzy_match is not None:
                        result.merges.append({"entity": entity.model_dump(), "existing_id": str(fuzzy_match["id"]), "strategy": "keep_latest_source"})
                        continue

                    result.inserts.append({"entity": entity.model_dump()})
            return result
        finally:
            logger.info("exit", agent="w4", latency_ms=int((time.perf_counter() - start) * 1000))

    def _find_exact(self, entity: NormalizedClinicalEntity, rows: list[Any]) -> Any | None:
        code = entity.snomed_code or entity.icd10_code or entity.loinc_code or entity.rxnorm_code
        if not code:
            return None
        for row in rows:
            candidate_codes = [row.get("snomed_code"), row.get("icd10_code"), row.get("loinc_code"), row.get("rxnorm_code")]
            if code in {c for c in candidate_codes if c}:
                return row
        return None

    def _find_fuzzy(self, display_name: str, rows: list[Any]) -> Any | None:
        for row in rows:
            candidate = str(row.get("display_name") or row.get("substance_name") or "")
            if candidate and fuzz.ratio(display_name.lower(), candidate.lower()) >= 88:
                return row
        return None

    def _detect_conflict(self, entity: NormalizedClinicalEntity, rows: list[Any]) -> dict[str, Any] | None:
        if entity.entity_type == "allergy":
            incoming_status = str(entity.attributes.get("status", "")).lower()
            if incoming_status == "no_known_allergy":
                for row in rows:
                    if str(row.get("status", "")).lower() == "active":
                        return {
                            "conflict_type": "allergy_disagreement",
                            "severity": "high",
                            "source_a": {"incoming": entity.model_dump()},
                            "source_b": {"existing_id": str(row.get("id"))},
                        }
        if entity.entity_type == "medication":
            for row in rows:
                same_rx = entity.rxnorm_code and entity.rxnorm_code == row.get("rxnorm_code")
                if not same_rx:
                    continue
                incoming_dose = str(entity.attributes.get("dose", "")).lower()
                existing_dose = str(row.get("dose", "")).lower()
                if incoming_dose and existing_dose and incoming_dose != existing_dose:
                    return {
                        "conflict_type": "med_disagreement",
                        "severity": "medium",
                        "source_a": {"incoming": entity.model_dump()},
                        "source_b": {"existing_id": str(row.get("id"))},
                    }
        if entity.entity_type == "condition":
            incoming_status = str(entity.attributes.get("status", "")).lower()
            now = datetime.now(UTC)
            for row in rows:
                same_code = (
                    (entity.snomed_code and entity.snomed_code == row.get("snomed_code"))
                    or (entity.icd10_code and entity.icd10_code == row.get("icd10_code"))
                )
                if not same_code:
                    continue
                existing_status = str(row.get("status", "")).lower()
                ingested_at = row.get("ingested_at") or now
                if isinstance(ingested_at, datetime) and (now - ingested_at) <= timedelta(days=180):
                    opposite = {incoming_status, existing_status} == {"active", "resolved"}
                    if opposite:
                        return {
                            "conflict_type": "diagnosis_disagreement",
                            "severity": "medium",
                            "source_a": {"incoming": entity.model_dump()},
                            "source_b": {"existing_id": str(row.get("id"))},
                        }
        return None
